from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

from app.services.ledger.replay import replay_ledger
from app.services.ledger.reconciliation import reconcile_ledger


def opening(**changes):
    return {
        "account_id": "demo",
        "as_of": "2026-08-31",
        "source_record_hash": "0" * 64,
        "cash_basis": "settled",
        "cash": {"KRW": "1000000", "USD": "1000"},
        "receivables": {"KRW": "0", "USD": "0"},
        "payables": {"KRW": "0", "USD": "0"},
        "positions": {},
        **changes,
    }


def event(**changes):
    return {
        "account_id": "demo",
        "event_key": "one",
        "revision": 1,
        "source_type": "statement",
        "source_key": "doc:1",
        "source_record_hash": "a" * 64,
        "event_type": "trade",
        "event_date": "2026-09-01",
        "effective_at": None,
        "observed_at": "2026-09-04T00:00:00+00:00",
        "timezone": "Asia/Seoul",
        "precision": "date_only",
        "quality": "verified",
        "currency": "USD",
        "market": "US",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": "2",
        "gross_amount": "200",
        "fee": "1",
        "tax": "0",
        "net_cash_amount": "-201",
        "settlement_date": "2026-09-03",
        "settlement_confirmed": True,
        **changes,
    }


def replay(rows, **kwargs):
    return replay_ledger(
        opening(),
        rows,
        as_of="2026-09-04",
        known_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
        **kwargs,
    )


def test_duplicate_replay_is_idempotent_and_settlement_is_not_a_second_trade():
    rows = [event(), event()]
    before = deepcopy(rows)
    result = replay(rows)
    assert result["balances"]["positions"] == {"US:AAPL:USD": Decimal("2")}
    assert result["balances"]["cash"]["USD"] == Decimal("799")
    assert result["balances"]["payables"]["USD"] == 0
    assert result["return_rate"] is None
    assert result == replay(rows)
    assert rows == before
    for journal in result["journals"]:
        assert sum(leg["amount"] for leg in journal["legs"]) == 0


def test_cumulative_execution_observations_are_not_trades():
    result = replay(
        [
            event(event_type="execution_aggregate", precision="aggregate"),
            event(
                event_type="execution_aggregate",
                precision="aggregate",
                revision=2,
                supersedes_hash="a" * 64,
                source_record_hash="b" * 64,
                quantity="5",
                gross_amount="510",
                net_cash_amount="-511",
            ),
        ]
    )
    assert result["balances"]["positions"] == {}
    assert result["balances"]["cash"]["USD"] == 1000
    assert result["status"] == "incomplete"
    assert len(result["evidence"]) == 2


def test_out_of_order_correction_reverses_previous_postings_once():
    correction = event(
        revision=2,
        supersedes_hash="a" * 64,
        source_record_hash="b" * 64,
        quantity="5",
        gross_amount="510",
        net_cash_amount="-511",
    )
    result = replay([correction, event()])
    assert result["balances"]["cash"]["USD"] == 489
    assert result["balances"]["positions"]["US:AAPL:USD"] == 5
    assert any(j["kind"] == "reversal" for j in result["journals"])
    assert result["balances"] == replay([event(), correction])["balances"]


def test_explicit_reversal_removes_trade_but_keeps_evidence():
    reversal = event(
        event_type="reversal", revision=2, supersedes_hash="a" * 64, source_record_hash="b" * 64
    )
    result = replay([event(), reversal])
    assert result["balances"]["cash"]["USD"] == 1000
    assert result["balances"]["positions"].get("US:AAPL:USD", 0) == 0
    assert len(result["evidence"]) == 2


def test_unknown_cost_and_revision_conflict_fail_closed():
    result = replay([event(), event(source_record_hash="b" * 64, fee=None)])
    assert result["status"] == "incomplete"
    assert result["balances"]["positions"] == {}
    assert replay([event(fee=None)])["balances"]["cash"]["USD"] == 1000


def test_invalid_correction_does_not_silently_reuse_old_revision():
    result = replay([event(), event(revision=2, supersedes_hash="a" * 64, fee=1.5)])
    assert result["status"] == "incomplete"
    assert result["balances"]["positions"] == {}


def test_unsettled_trade_preserves_cash_and_liability():
    result = replay([event(settlement_confirmed=False)])
    assert result["balances"]["cash"]["USD"] == 1000
    assert result["balances"]["payables"]["USD"] == 201
    assert result["status"] == "incomplete"


def test_pre_settlement_date_does_not_move_cash():
    result = replay([event(settlement_date="2026-09-07", settlement_confirmed=False)])
    assert result["balances"]["cash"]["USD"] == 1000
    assert result["balances"]["payables"]["USD"] == 201


def test_dividend_and_fx_legs_reconcile_without_external_deposit():
    dividend = event(
        event_type="dividend", gross_amount="10", fee="0", tax="1.5", net_cash_amount="8.5"
    )
    fx = event(
        event_type="fx_conversion",
        event_key="fx",
        source_key="doc:2",
        source_record_hash="b" * 64,
        currency="KRW",
        market=None,
        symbol=None,
        quantity=None,
        gross_amount="140000",
        fee="100",
        tax="0",
        net_cash_amount="-140100",
        counter_currency="USD",
        counter_amount="100",
    )
    result = replay([dividend, fx])
    assert result["balances"]["cash"] == {"USD": Decimal("1108.5"), "KRW": Decimal("859900")}
    assert result["external_flows"] == {"USD": Decimal("0"), "KRW": Decimal("0")}


def test_different_real_rows_with_equal_values_are_not_deduplicated():
    second = event(event_key="two", source_key="doc:2", source_record_hash="b" * 64)
    result = replay([event(), second])
    assert result["balances"]["positions"]["US:AAPL:USD"] == 4


def test_future_observation_and_future_event_are_not_used():
    result = replay(
        [
            event(observed_at="2026-10-01T00:00:00Z"),
            event(event_key="future", event_date="2026-10-01", settlement_date=None),
        ]
    )
    assert result["balances"]["positions"] == {}


def test_reconciliation_reports_residual_and_incomplete_even_if_balances_match():
    result = replay([event()])
    observed = opening(
        as_of="2026-09-04", cash={"KRW": "1000000", "USD": "800"}, positions={"US:AAPL:USD": "2"}
    )
    check = reconcile_ledger(result, observed)
    assert check["status"] == "mismatch"
    assert check["residuals"]["cash"]["USD"] == 1
    incomplete = replay([event(quality="provisional")])
    same = opening(as_of="2026-09-04")
    assert reconcile_ledger(incomplete, same)["status"] == "incomplete"


def test_same_source_row_cannot_be_posted_under_two_event_keys():
    result = replay([event(), event(event_key="renamed")])
    assert result["status"] == "incomplete"
    assert result["balances"]["positions"] == {}


def test_sell_leaves_receivable_until_confirmed_settlement_and_no_invented_profit():
    base = opening(positions={"US:AAPL:USD": "3"})
    sold = event(
        side="SELL",
        gross_amount="220",
        fee="1",
        tax="2",
        net_cash_amount="217",
        settlement_confirmed=False,
    )
    result = replay_ledger(
        base, [sold], as_of="2026-09-04", known_at=datetime(2026, 9, 10, tzinfo=timezone.utc)
    )
    assert result["balances"]["positions"]["US:AAPL:USD"] == 1
    assert result["balances"]["receivables"]["USD"] == 217
    assert result["balances"]["cash"]["USD"] == 1000
    assert result["realized_profit_loss"] is None


def test_deposits_are_external_flow_and_withdrawal_cost_is_separate():
    incoming = event(
        event_type="deposit", gross_amount="100", fee="0", tax="0", net_cash_amount="100"
    )
    outgoing = event(
        event_type="withdrawal",
        event_key="withdraw",
        source_key="doc:2",
        source_record_hash="b" * 64,
        gross_amount="50",
        fee="1",
        tax="0",
        net_cash_amount="-51",
    )
    result = replay([incoming, outgoing])
    assert result["balances"]["cash"]["USD"] == 1049
    assert result["external_flows"]["USD"] == 50


def test_negative_closing_position_is_reported():
    result = replay([event(side="SELL", net_cash_amount="199")])
    assert result["status"] == "incomplete"
    assert any(issue["reason"] == "negative_balance" for issue in result["issues"])


def test_invalid_identifier_is_isolated_without_crashing():
    result = replay([event(event_key=[]), event()])
    assert result["status"] == "incomplete"
    assert result["balances"]["positions"]["US:AAPL:USD"] == 2


def test_ambiguous_date_correction_blocks_previous_revision():
    result = replay(
        [
            event(),
            event(
                revision=2,
                supersedes_hash="a" * 64,
                source_record_hash="b" * 64,
                timezone="America/New_York",
            ),
        ]
    )
    assert result["balances"]["positions"] == {}


def test_share_count_adjustment_does_not_create_cash():
    adjusted = event(
        event_type="corporate_action",
        event_key="split",
        source_key="doc:2",
        source_record_hash="b" * 64,
        quantity="2",
    )
    result = replay([event(), adjusted])
    assert result["balances"]["positions"]["US:AAPL:USD"] == 4
    assert result["balances"]["cash"]["USD"] == 799
