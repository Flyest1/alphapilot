from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.db.ledger_repository import LedgerRepository
from app.services.ledger.statement import normalize_statement

RAW = b"date,amount,memo\n2026-09-10,1.2300,PRIVATE\n"


class Client:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def rpc(self, name, params):
        self.calls.append((name, deepcopy(params)))
        if name == self.fail:
            raise RuntimeError("database unavailable")
        return SimpleNamespace(
            execute=lambda: SimpleNamespace(data={"run_key": params["p_run_key"]})
        )


MAPPING = {
    "version": "statement_csv_v1",
    "columns": {"event_date": "date", "net_cash_amount": "amount"},
    "constants": {
        "event_type": "deposit",
        "currency": "USD",
        "timezone": "Asia/Seoul",
        "precision": "date_only",
    },
}


def batch(raw=RAW):
    return normalize_statement(
        raw, account_id="account", observed_at="2026-09-11T12:00:00+09:00", mapping=MAPPING
    )


def test_capture_precedes_publish_and_keeps_only_source_metadata():
    client = Client()
    repo = LedgerRepository(client)
    first = repo.import_statement(
        batch(),
        raw=RAW,
        mapping=MAPPING,
        account_id="account",
        observed_at="2026-09-11T12:00:00+09:00",
    )
    again = repo.import_statement(
        batch(),
        raw=RAW,
        mapping=MAPPING,
        account_id="account",
        observed_at="2026-09-11T12:00:00+09:00",
    )
    assert first == again
    assert [name for name, _ in client.calls[:2]] == [
        "ledger_capture_import",
        "ledger_publish_import",
    ]
    source = client.calls[0][1]["p_sources"][0]
    assert set(source) == {"source_key", "payload_hash", "document_hash", "row_number"}
    assert "PRIVATE" not in repr(client.calls)
    assert client.calls[1][1]["p_events"][0]["net_cash_amount"] == "1.2300"


@pytest.mark.parametrize(
    "field,value",
    [("account_id", "other"), ("source_record_hash", "b" * 64), ("source_key", "missing")],
)
def test_bad_evidence_link_is_rejected_before_db(field, value):
    rows = batch()
    rows["events"][0][field] = value
    client = Client()
    with pytest.raises(ValueError):
        LedgerRepository(client).import_statement(
            rows,
            raw=RAW,
            mapping=MAPPING,
            account_id="account",
            observed_at="2026-09-11T12:00:00+09:00",
        )
    assert client.calls == []


def test_publish_failure_leaves_capture_retryable():
    client = Client(fail="ledger_publish_import")
    with pytest.raises(RuntimeError):
        LedgerRepository(client).import_statement(
            batch(),
            raw=RAW,
            mapping=MAPPING,
            account_id="account",
            observed_at="2026-09-11T12:00:00+09:00",
        )
    assert len(client.calls) == 2
    assert client.calls[0][0] == "ledger_capture_import"


def test_normalized_amount_cannot_be_changed_while_keeping_source_hash():
    rows = batch()
    rows["events"][0]["net_cash_amount"] = "999"
    client = Client()
    with pytest.raises(ValueError):
        LedgerRepository(client).import_statement(
            rows,
            raw=RAW,
            mapping=MAPPING,
            account_id="account",
            observed_at="2026-09-11T12:00:00+09:00",
        )
    assert client.calls == []


def test_invalid_rows_and_empty_import_do_not_claim_complete():
    raw = RAW.replace(b"2026-09-10", b"invalid-date")
    rows = batch(raw)
    client = Client()
    LedgerRepository(client).import_statement(
        rows,
        raw=raw,
        mapping=MAPPING,
        account_id="account",
        observed_at="2026-09-11T12:00:00+09:00",
    )
    result = client.calls[-1][1]["p_result"]
    assert result["status"] == "rejected" and result["coverage_verified"] is False


def test_duplicate_first_row_cannot_mask_missing_second_row():
    raw = RAW + b"2026-09-10,2.0000,SECOND\n"
    rows = batch(raw)
    rows["events"][1] = rows["events"][0]
    client = Client()
    with pytest.raises(ValueError):
        LedgerRepository(client).import_statement(
            rows,
            raw=raw,
            mapping=MAPPING,
            account_id="account",
            observed_at="2026-09-11T12:00:00+09:00",
        )
    assert client.calls == []
