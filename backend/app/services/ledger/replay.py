"""Deterministic end-of-day cash/quantity replay, not a trading or return engine."""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, localcontext
from zoneinfo import ZoneInfo

from app.models.account_ledger import LedgerBalance
from app.services.ledger.validation import validate_events

ZERO = Decimal("0")
ACCOUNT_ZONE = ZoneInfo("Asia/Seoul")


def _event_day(event):
    if event.effective_at is not None:
        return event.effective_at.astimezone(ACCOUNT_ZONE).date()
    if event.timezone != "Asia/Seoul":
        raise ValueError("date_only_timezone_ambiguous")
    return event.event_date


def _book(event, cutoff):
    if event.quality != "verified":
        raise ValueError("unverified_evidence")
    if event.event_type == "execution_aggregate" or event.precision == "aggregate":
        raise ValueError("aggregate_is_not_a_trade")
    if event.event_type == "reversal":
        return [], {}, {}
    positions, flows = {}, {}
    legs = []

    def leg(account, amount, currency=None):
        legs.append({"account": account, "currency": currency or event.currency, "amount": amount})

    if event.event_type in {"security_transfer", "corporate_action"}:
        quantity = event.quantity
        if event.event_type == "security_transfer" and event.side == "OUT":
            quantity = -quantity
        positions[f"{event.market}:{event.symbol}:{event.currency}"] = quantity
        return legs, positions, flows
    if any(
        value is None for value in (event.gross_amount, event.fee, event.tax, event.net_cash_amount)
    ):
        raise ValueError("missing_cash_or_cost_evidence")
    gross, fee, tax = event.gross_amount, event.fee, event.tax
    outgoing = event.event_type in {"withdrawal", "fx_conversion"} or (
        event.event_type == "trade" and event.side == "BUY"
    )
    expected = -gross - fee - tax if outgoing else gross - fee - tax
    if expected != event.net_cash_amount:
        raise ValueError("cash_components_do_not_reconcile")
    leg("fees", fee)
    leg("taxes", tax)
    if event.event_type == "trade":
        sign = Decimal("1") if event.side == "BUY" else Decimal("-1")
        positions[f"{event.market}:{event.symbol}:{event.currency}"] = sign * event.quantity
        leg("security_notional_clearing", sign * gross)
        settled = (
            event.settlement_confirmed
            and event.settlement_date is not None
            and (event.settlement_date <= cutoff)
        )
        leg("cash" if settled else ("payables" if outgoing else "receivables"), expected)
    else:
        leg("cash", expected)
        if event.event_type in {"deposit", "withdrawal"}:
            flow = -gross if outgoing else gross
            flows[event.currency] = flow
            leg("external_capital", -flow)
        elif event.event_type in {"dividend", "interest"}:
            leg("income", -gross)
        elif event.event_type == "fx_conversion":
            if event.counter_amount is None or event.counter_amount <= 0 or gross <= 0:
                raise ValueError("missing_fx_counter_leg")
            leg("fx_clearing", gross)
            leg("cash", event.counter_amount, event.counter_currency)
            leg("fx_clearing", -event.counter_amount, event.counter_currency)
    return legs, positions, flows


def replay_ledger(opening: dict, rows: list[dict], *, as_of: str, known_at: datetime) -> dict:
    baseline = LedgerBalance.model_validate(opening)
    cutoff = date.fromisoformat(as_of)
    if cutoff < baseline.as_of or known_at.tzinfo is None:
        raise ValueError("Invalid replay window or knowledge timestamp")
    if cutoff > known_at.astimezone(ACCOUNT_ZONE).date():
        raise ValueError("Closing date cannot be after knowledge timestamp")
    validated = validate_events(rows)
    issues = list(validated["errors"])
    blocked = {
        rows[error["row"]].get("event_key")
        for error in issues
        if isinstance(rows[error["row"]], dict)
        and isinstance(rows[error["row"]].get("event_key"), str)
    }
    balances = {
        key: dict(getattr(baseline, key))
        for key in ("cash", "positions", "receivables", "payables")
    }
    groups = defaultdict(list)
    source_keys = {}
    evidence = []
    for event in validated["events"]:
        evidence.append(event.model_dump(mode="json"))
        if event.account_id != baseline.account_id:
            issues.append({"event_key": event.event_key, "reason": "account_mismatch"})
            continue
        if event.observed_at > known_at:
            continue
        try:
            day = _event_day(event)
        except ValueError as exc:
            issues.append({"event_key": event.event_key, "reason": str(exc)})
            blocked.add(event.event_key)
            continue
        if day <= cutoff:
            source_key = (event.source_type, event.source_key)
            previous_key = source_keys.get(source_key)
            if previous_key is not None and previous_key != event.event_key:
                blocked.update({previous_key, event.event_key})
                issues.append({"event_key": event.event_key, "reason": "source_row_reused"})
            source_keys[source_key] = event.event_key
            groups[event.event_key].append(event)
    journals, posted = [], []
    external_flows = {"KRW": ZERO, "USD": ZERO}
    with localcontext() as context:
        context.prec = 60

        def apply(book, event, kind, multiplier=Decimal("1")):
            legs, positions, flows = book
            for currency in ("KRW", "USD"):
                selected = [
                    {**item, "amount": item["amount"] * multiplier}
                    for item in legs
                    if item["currency"] == currency
                ]
                if not selected:
                    continue
                if sum((item["amount"] for item in selected), ZERO) != 0:
                    raise ValueError("Unbalanced journal")
                journals.append(
                    {
                        "event_key": event.event_key,
                        "revision": event.revision,
                        "evidence_hash": event.source_record_hash,
                        "event_date": _event_day(event).isoformat(),
                        "observed_at": event.observed_at.isoformat(),
                        "kind": kind,
                        "currency": currency,
                        "legs": selected,
                    }
                )
                for item in selected:
                    account = item["account"]
                    if account in {"cash", "receivables", "payables"}:
                        balances[account][currency] += item["amount"] * (
                            -1 if account == "payables" else 1
                        )
            for key, quantity in positions.items():
                balances["positions"][key] = (
                    balances["positions"].get(key, ZERO) + quantity * multiplier
                )
            for currency, flow in flows.items():
                external_flows[currency] += flow * multiplier

        for key in sorted(groups, key=lambda key: (min(_event_day(e) for e in groups[key]), key)):
            if key in blocked:
                continue
            revisions = {}
            try:
                for event in groups[key]:
                    existing = revisions.get(event.revision)
                    if existing and existing.model_dump(
                        exclude={"observed_at"}
                    ) != event.model_dump(exclude={"observed_at"}):
                        raise ValueError("conflicting_revision")
                    if existing is None or event.observed_at < existing.observed_at:
                        revisions[event.revision] = event
                chain = [revisions[n] for n in sorted(revisions)]
                if [event.revision for event in chain] != list(range(1, len(chain) + 1)):
                    raise ValueError("missing_revision")
                for previous, event in zip(chain, chain[1:]):
                    if event.supersedes_hash != previous.source_record_hash:
                        raise ValueError("broken_revision_link")
                    if event.observed_at < previous.observed_at:
                        raise ValueError("revision_observation_order_conflict")
                dates = [_event_day(event) for event in chain]
                if max(dates) <= baseline.as_of:
                    continue
                if min(dates) <= baseline.as_of:
                    raise ValueError("correction_crosses_opening_boundary")
                final = chain[-1]
                final_book = _book(final, cutoff)
            except ValueError as exc:
                issues.append({"event_key": key, "reason": str(exc)})
                continue
            previous_book = None
            for event in chain:
                if previous_book is not None:
                    apply(previous_book, event, "reversal", Decimal("-1"))
                try:
                    book = final_book if event is final else _book(event, cutoff)
                except ValueError:
                    book = ([], {}, {})
                apply(book, event, "posting")
                previous_book = book
            posted.append(key)
            if final.event_type == "trade" and (
                final.settlement_date is None
                or (final.settlement_date <= cutoff and not final.settlement_confirmed)
            ):
                issues.append({"event_key": key, "reason": "unconfirmed_settlement"})
            if final.event_type == "security_transfer":
                issues.append({"event_key": key, "reason": "transfer_value_not_modeled"})
    for name, values in balances.items():
        if any(value < 0 for value in values.values()):
            issues.append({"reason": "negative_balance", "component": name})
    return {
        "policy_version": "local_ledger_v1",
        "account_id": baseline.account_id,
        "as_of": as_of,
        "known_at": known_at.isoformat(),
        "timezone": "Asia/Seoul",
        "opening_hash": baseline.source_record_hash,
        "balances": balances,
        "external_flows": external_flows,
        "journals": journals,
        "evidence": evidence,
        "posted_event_keys": posted,
        "issues": issues,
        "status": "incomplete" if issues else "replayed",
        "return_rate": None,
        "realized_profit_loss": None,
        "coverage_verified": False,
        "limitations": [
            "End-of-day cash and quantity replay, not intraday solvency verification.",
            "Security notional clearing is not cost basis or realized profit.",
            "Statement completeness and economic duplicates across sources need review.",
        ],
    }
