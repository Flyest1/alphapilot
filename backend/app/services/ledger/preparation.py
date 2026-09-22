"""Local operating-ledger preparation; never certifies coverage or writes to a DB."""

import csv
from datetime import date, timedelta
from decimal import Decimal
import hashlib
from io import StringIO
from itertools import islice
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, TypeAdapter

from app.models.account_ledger import Identifier, LedgerBalance, LedgerEvent
from app.services.ledger.reconciliation import reconcile_ledger
from app.services.ledger.replay import _event_day, replay_ledger
from app.services.ledger.review import prepare_replay
from app.services.ledger.statement import MAX_DOCUMENT_BYTES, normalize_statement

CHECKS = (
    "account_and_period",
    "cash_flows",
    "fees_and_taxes",
    "fx_and_corporate_actions",
    "settlement_and_corrections",
    "overlapping_documents",
)
MAX_STATEMENTS = 24
MAX_ROWS = 10000


def preparation_template():
    return {
        "version": "ledger_preparation_v1",
        "account_id": None,
        "period_start": None,
        "period_end": None,
        "observed_at": None,
        "synthetic": False,
        "opening": {"balance": None, "evidence": None},
        "closing": {"balance": None, "evidence": None},
        "statements": [],
        "checks": dict.fromkeys(CHECKS, False),
    }


def _read(path):
    if not path.is_file():
        raise ValueError("Regular file required")
    with path.open("rb") as stream:
        raw = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("Input exceeds 5 MiB")
    return raw


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=unique)


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("ISO date required")
    return date.fromisoformat(value)


def _shape(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError("Unexpected fields")


def _safe_json(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError("Unsupported report value")


def check_preparation(manifest_path: Path):
    result = {
        "version": "ledger_preparation_v1",
        "status": "blocked",
        "stored": False,
        "synthetic": None,
        "coverage_verified": False,
        "evidence_verified_by_tool": False,
        "return_rate": None,
        "realized_profit_loss": None,
        "blockers": [],
        "input_hashes": {},
        "documents": [],
        "duplicate_candidates": 0,
        "reconciliation": None,
    }

    def block(code, **context):
        result["blockers"].append({"code": code, **context})

    manifest_path = Path(manifest_path).resolve()
    base = manifest_path.parent

    def source(relative, label):
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise ValueError("Relative file required")
        path = (base / relative).resolve()
        path.relative_to(base)
        raw = _read(path)
        result["input_hashes"][label] = hashlib.sha256(raw).hexdigest()
        return raw

    try:
        raw = _read(manifest_path)
        result["input_hashes"]["manifest"] = hashlib.sha256(raw).hexdigest()
        manifest = _json(raw)
        _shape(manifest, preparation_template())
        if (
            manifest["version"] != "ledger_preparation_v1"
            or type(manifest["synthetic"]) is not bool
        ):
            raise ValueError("Invalid version or synthetic flag")
        _shape(manifest["checks"], CHECKS)
        if any(type(value) is not bool for value in manifest["checks"].values()):
            raise ValueError("Checks require explicit booleans")
        for name in ("opening", "closing"):
            _shape(manifest[name], {"balance", "evidence"})
        statements = manifest["statements"]
        if not isinstance(statements, list) or len(statements) > MAX_STATEMENTS:
            raise ValueError("Invalid statement list")
        for item in statements:
            _shape(item, {"csv", "mapping", "period_start", "period_end"})
        result["synthetic"] = manifest["synthetic"]
    except (ValueError, OSError, TypeError, RecursionError):
        block("invalid_manifest")
        return result

    for check, confirmed in manifest["checks"].items():
        if not confirmed:
            block("unchecked_material", check=check)
    account = manifest["account_id"]
    try:
        TypeAdapter(Identifier).validate_python(account)
    except ValueError:
        block("missing_account")
    start = end = known_at = None
    try:
        start, end = _day(manifest["period_start"]), _day(manifest["period_end"])
        if start > end:
            raise ValueError("Reversed period")
    except ValueError:
        block("missing_period")
        start = end = None
    try:
        if not isinstance(manifest["observed_at"], str):
            raise ValueError("Timestamp required")
        known_at = TypeAdapter(AwareDatetime).validate_python(manifest["observed_at"])
        # End-of-day balances cannot be accepted while the closing day is still open.
        if end is not None and known_at.astimezone(ZoneInfo("Asia/Seoul")).date() <= end:
            raise ValueError("Closing day not elapsed")
    except ValueError:
        block("invalid_observation_time")
        known_at = None

    balances = {}
    for name in ("opening", "closing"):
        item = manifest[name]
        if not item["balance"] or not item["evidence"]:
            block("missing_" + name)
            continue
        try:
            value = LedgerBalance.model_validate(_json(source(item["balance"], name + "_balance")))
            evidence = source(item["evidence"], name + "_evidence")
            if value.source_record_hash != hashlib.sha256(evidence).hexdigest():
                raise ValueError("Evidence hash mismatch")
            expected = start - timedelta(days=1) if start and name == "opening" else end
            if value.account_id != account or expected is None or value.as_of != expected:
                raise ValueError("Account/date mismatch")
            balances[name] = value.model_dump(mode="json")
        except (ValueError, OSError, TypeError, OverflowError, RecursionError):
            block("invalid_" + name)

    if not statements:
        block("missing_statements")
    if not account or start is None or end is None or known_at is None:
        return result
    events, imports, periods, seen = [], [], [], set()
    total_rows = 0
    for index, item in enumerate(statements, 1):
        try:
            first, last = _day(item["period_start"]), _day(item["period_end"])
            if not start <= first <= last <= end:
                raise ValueError("Statement period outside requested window")
            raw = source(item["csv"], f"statement_{index}")
            rows = list(islice(csv.reader(StringIO(raw.decode("utf-8-sig"))), MAX_ROWS + 2))
            total_rows += max(0, len(rows) - 1)
            if len(rows) > MAX_ROWS + 1 or total_rows > MAX_ROWS:
                raise ValueError("Row limit exceeded")
            mapping = _json(source(item["mapping"], f"mapping_{index}"))
            batch = normalize_statement(
                raw, account_id=account, observed_at=manifest["observed_at"], mapping=mapping
            )
            result["documents"].append(
                {"index": index, "events": len(batch["events"]), "errors": batch["errors"]}
            )
            if batch["document_hash"] in seen:
                block("repeated_document", document=index)
                continue
            seen.add(batch["document_hash"])
            periods.append((first, last))
            if batch["errors"] or not batch["events"]:
                block("invalid_statement_rows", document=index)
            for row in batch["events"]:
                try:
                    if not first <= _event_day(LedgerEvent.model_validate(row)) <= last:
                        block("event_outside_period", document=index)
                except ValueError:
                    block("ambiguous_event_date", document=index)
            events.extend(batch["events"])
            imports.append(
                {
                    "run_key": str(index),
                    "manifest": {
                        "observed_at": manifest["observed_at"],
                        "document_hash": batch["document_hash"],
                        "source_count": len(batch["sources"]),
                    },
                    "result": {
                        "status": "partial" if batch["errors"] else "validated",
                        "errors": batch["errors"],
                    },
                    "events": batch["events"],
                }
            )
        except (ValueError, OSError, TypeError, csv.Error, RecursionError):
            block("invalid_statement", document=index)
    through = start.toordinal() - 1
    for first, last in sorted(periods):
        if first.toordinal() > through + 1:
            break
        through = max(through, last.toordinal())
    if through < end.toordinal():
        block("statement_period_gap")
    if len(balances) == 2:
        try:
            projection = prepare_replay(
                {"events": events, "imports": imports, "reviews": []},
                account_id=account,
                opening_date=balances["opening"]["as_of"],
                as_of=end.isoformat(),
                known_at=known_at,
            )
            result["duplicate_candidates"] = len(projection["duplicate_candidates"])
            if projection["issues"]:
                block("review_issues")
            replay = replay_ledger(
                balances["opening"], projection["events"], as_of=end.isoformat(), known_at=known_at
            )
            if replay["issues"]:
                block("replay_issues")
            comparison = reconcile_ledger(replay, balances["closing"])
            # Do not export free-text event IDs or account details in the preparation report.
            comparison["issues"] = [{"reason": issue["reason"]} for issue in replay["issues"]]
            result["reconciliation"] = comparison
            if not comparison["balances_match"]:
                block("balance_mismatch")
        except (ValueError, TypeError):
            block("reconciliation_failed")
    if not result["blockers"]:
        result["status"] = "ready_for_review"
    return json.loads(json.dumps(result, default=_safe_json, allow_nan=False))
