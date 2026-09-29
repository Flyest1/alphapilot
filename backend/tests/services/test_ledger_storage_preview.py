from copy import deepcopy
import hashlib

import pytest

from app.models.account_ledger import LedgerBalance
from app.services.ledger.statement import normalize_statement
from app.services.ledger.storage_preview import preview_storage, proposed_import

ACCOUNT = "preview-local"
TIME = "2026-09-03T10:00:00+09:00"
MAPPING = {
    "version": "statement_csv_v1",
    "columns": {"event_date": "day", "gross_amount": "gross", "net_cash_amount": "net"},
    "constants": {
        "event_type": "deposit",
        "currency": "USD",
        "timezone": "Asia/Seoul",
        "precision": "date_only",
        "quality": "verified",
        "fee": "0",
        "tax": "0",
    },
}


def batch(raw=b"day,gross,net\n2026-09-01,10,10\n", mapping=None, observed_at=TIME):
    return normalize_statement(
        raw, account_id=ACCOUNT, observed_at=observed_at, mapping=mapping or MAPPING
    )


def context(amount="10"):
    def balance(day, value):
        return LedgerBalance.model_validate(
            {
                "account_id": ACCOUNT,
                "as_of": day,
                "source_record_hash": "a" * 64,
                "cash_basis": "settled",
                "cash": {"KRW": "0", "USD": value},
                "receivables": {"KRW": "0", "USD": "0"},
                "payables": {"KRW": "0", "USD": "0"},
                "positions": {},
            }
        ).model_dump(mode="json")

    return {
        "account_id": ACCOUNT,
        "observed_at": TIME,
        "opening": balance("2026-08-31", "0"),
        "closing": balance("2026-09-02", amount),
        "as_of": "2026-09-02",
        "batches": [batch()],
    }


def empty():
    return {"account_id": ACCOUNT, "snapshot": {"events": [], "imports": [], "reviews": []}}


def stored(value=None):
    value = value or batch()
    item = proposed_import(value, account_id=ACCOUNT, observed_at=value["events"][0]["observed_at"])
    snapshot = empty()
    snapshot["snapshot"].update(events=value["events"], imports=[item])
    return snapshot


def test_new_material_preview_reconciles_and_does_not_mutate_either_input():
    inputs, snapshot = context(), empty()
    original = deepcopy([inputs, snapshot])
    result = preview_storage(inputs, snapshot)
    assert result["status"] == "ready_for_review"
    assert result["documents"][0]["new_events"] == 1
    assert result["reconciliation"]["balances_match"] is True
    assert result["stored"] is False and result["coverage_verified"] is False
    assert result["return_rate"] is None
    assert [inputs, snapshot] == original


def test_exact_reimport_is_idempotent_in_preview():
    result = preview_storage(context(), stored())
    assert result["status"] == "ready_for_review"
    assert result["documents"][0]["status"] == "already_imported"
    assert result["reconciliation"]["residuals"]["cash"]["USD"] == "0"


def test_later_observation_preserves_first_event_and_earlier_observation_is_blocked():
    snapshot = stored(batch(observed_at="2026-09-02T10:00:00+09:00"))
    result = preview_storage(context(), snapshot)
    assert result["documents"][0]["reobserved_events"] == 1
    assert result["status"] == "ready_for_review"
    late = stored(batch(observed_at="2026-09-04T10:00:00+09:00"))
    result = preview_storage(context(), late)
    assert "earlier_observation" in {x["code"] for x in result["blockers"]}


def test_same_revision_with_changed_payload_is_blocked_before_projection():
    inputs = context()
    mapping = deepcopy(MAPPING)
    mapping["constants"]["quality"] = "provisional"
    inputs["batches"] = [batch(mapping=mapping)]
    result = preview_storage(inputs, stored())
    assert "conflicting_revision" in {x["code"] for x in result["blockers"]}
    assert result["status"] == "blocked"


def test_economic_duplicate_against_another_document_requires_review():
    old = batch(b"day,gross,net,memo\n2026-09-01,10,10,PRIVATE_MEMO\n")
    result = preview_storage(context(), stored(old))
    assert result["duplicate_candidates"] == 1
    assert result["status"] == "blocked"
    assert "PRIVATE_MEMO" not in repr(result)


def test_existing_pending_import_prevents_clean_preview():
    snapshot = stored()
    snapshot["snapshot"]["imports"][0]["result"] = None
    snapshot["snapshot"]["imports"][0]["events"] = []
    snapshot["snapshot"]["events"] = []
    assert preview_storage(context(), snapshot)["status"] == "blocked"


@pytest.mark.parametrize("change", ["account", "malformed", "foreign_event", "missing_event"])
def test_bad_snapshot_fails_closed(change):
    snapshot = stored()
    if change == "account":
        snapshot["account_id"] = "other"
    elif change == "malformed":
        snapshot["snapshot"]["reviews"] = None
    elif change == "foreign_event":
        snapshot["snapshot"]["events"][0]["account_id"] = "other"
    else:
        snapshot["snapshot"]["events"] = []
    with pytest.raises(ValueError):
        preview_storage(context(), snapshot)


def test_snapshot_changes_are_bound_to_different_hashes():
    first = preview_storage(context(), empty())
    second = preview_storage(context(), stored())
    assert first["snapshot_hash"] != second["snapshot_hash"]
    assert len(first["snapshot_hash"]) == hashlib.sha256().digest_size * 2


def test_existing_explicit_duplicate_review_is_preserved_in_preview():
    snapshot = stored(batch(b"day,gross,net,memo\n2026-09-01,10,10,PRIVATE_MEMO\n"))
    left, right = sorted(
        [snapshot["snapshot"]["events"][0]["event_key"], batch()["events"][0]["event_key"]]
    )
    snapshot["snapshot"]["reviews"] = [
        {
            "account_id": ACCOUNT,
            "review_key": "a" * 64,
            "revision": 1,
            "reviewed_at": TIME,
            "request": {
                "kind": "duplicate_review",
                "decision": "duplicate",
                "reason_code": "same_transaction",
                "left_event_key": left,
                "right_event_key": right,
                "left_revision": 1,
                "right_revision": 1,
            },
        }
    ]
    result = preview_storage(context(), snapshot)
    assert result["duplicate_candidates"] == 1
    assert result["status"] == "ready_for_review"
    assert result["reconciliation"]["balances_match"] is True


@pytest.mark.parametrize("valid_chain", [True, False])
def test_correction_uses_stored_prior_revision_and_rejects_broken_chain(valid_chain):
    old = batch()
    mapping = deepcopy(MAPPING)
    mapping["constants"].update(
        event_key=old["events"][0]["event_key"],
        revision="2",
        supersedes_hash=old["events"][0]["source_record_hash"] if valid_chain else "b" * 64,
    )
    inputs = context("12")
    inputs["batches"] = [batch(b"day,gross,net\n2026-09-01,12,12\n", mapping=mapping)]
    result = preview_storage(inputs, stored(old))
    assert result["status"] == ("ready_for_review" if valid_chain else "blocked")
    assert result["documents"][0]["new_revisions"] == 1


def test_read_snapshot_calls_only_get_rpc():
    from types import SimpleNamespace
    from app.db.ledger_repository import LedgerRepository

    calls = []

    class Client:
        def rpc(self, name, params, **options):
            calls.append((name, params, options))
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=empty()["snapshot"]))

    assert LedgerRepository(Client()).read_review_snapshot(ACCOUNT) == empty()
    assert calls == [("ledger_read_review_state", {"p_account_id": ACCOUNT}, {"get": True})]
