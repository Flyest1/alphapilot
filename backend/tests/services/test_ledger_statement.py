import hashlib
import json

import pytest

from app.services.ledger.statement import normalize_statement


def mapping():
    return {
        "version": "statement_csv_v1",
        "columns": {"event_date": "date", "net_cash_amount": "amount"},
        "constants": {
            "event_type": "deposit",
            "currency": "USD",
            "timezone": "Asia/Seoul",
            "precision": "date_only",
        },
    }


def normalize(raw, config=None):
    return normalize_statement(
        raw,
        account_id="account",
        observed_at="2026-09-11T12:00:00+09:00",
        mapping=config or mapping(),
    )


def test_stable_import_and_distinct_identical_rows_preserve_unknown_cost():
    raw = b"date,amount\n2026-09-10,1.2300\n2026-09-10,1.2300\n"
    result = normalize(raw)
    assert normalize(raw) == result
    assert result["document_hash"] == hashlib.sha256(raw).hexdigest()
    first, second = result["events"]
    assert first["source_key"] != second["source_key"]
    assert first["net_cash_amount"] == "1.2300"
    assert first["fee"] is None and first["tax"] is None
    assert first["quality"] == "provisional"
    assert result["coverage_verified"] is False
    assert result["sources"][0]["event_key_basis"] == "document_row"
    assert first["source_record_hash"] == second["source_record_hash"]


def test_extraneous_secrets_are_excluded_even_from_rejected_rows():
    result = normalize(b"date,amount,secret\n2026-09-10,1,SECRET\nbad,1,SECRET\n")
    assert len(result["events"]) == 1
    assert len(result["sources"]) == 2
    assert "SECRET" not in json.dumps(result)
    assert result["sources"][1]["payload"] == {}
    assert result["errors"][0]["row"] == 2


@pytest.mark.parametrize(
    "raw",
    [
        b"date,date\n1,2\n",
        b"date,amount\n2026-09-10\n",
        b"date,amount\n2026-09-10,1,2\n",
        b"date,other\n2026-09-10,1\n",
        b"date,\n2026-09-10,1\n",
        b"\xff",
        b"x" * (5 * 1024 * 1024 + 1),
    ],
    ids=["duplicate", "short", "wide", "missing", "empty", "encoding", "oversized"],
)
def test_malformed_document_rejected(raw):
    with pytest.raises(ValueError):
        normalize(raw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_key", "fake"),
        ("account_id", "fake"),
        ("memo", "SECRET"),
        ("fee", 0.1),
    ],
)
def test_bad_mapping_rejected(field, value):
    config = mapping()
    config["constants"][field] = value
    with pytest.raises(ValueError):
        normalize(b"date,amount\n2026-09-10,1\n", config)


def test_explicit_value_maps_and_stable_event_key():
    config = mapping()
    config["columns"].update({"event_key": "id", "quality": "review"})
    config["value_maps"] = {"quality": {"checked": "verified"}}
    result = normalize(b"date,amount,id,review\n2026-09-10,1,entry-1,checked\n", config)
    assert result["events"][0]["quality"] == "verified"
    assert result["events"][0]["event_key"] == "entry-1"
    assert result["sources"][0]["event_key_basis"] == "mapped"


@pytest.mark.parametrize("amount", ["1,000", "1e3", "+10", " 10"])
def test_amount_formats_are_not_inferred(amount):
    result = normalize(f'date,amount\n2026-09-10,"{amount}"\n'.encode())
    assert result["events"] == []
    assert result["errors"]


def test_utf8_bom_and_raw_row_hash_preserve_original_values():
    raw = "\ufeffdate,amount,비고\n2026-09-10,1.00,개인\n".encode()
    result = normalize(raw)
    expected = hashlib.sha256(
        json.dumps(
            {"date": "2026-09-10", "amount": "1.00", "비고": "개인"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert result["sources"][0]["payload_hash"] == expected
    assert "개인" not in json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize(
    "change",
    [
        {"version": "toss"},
        {"extra": "secret"},
        {"columns": {"quantity": ""}},
        {"value_maps": {"fee": {"x": "0"}}},
        {"value_maps": {"net_cash_amount": {"x": 0}}},
    ],
)
def test_mapping_schema_rejects_unsupported_configuration(change):
    config = mapping()
    config.update(change)
    with pytest.raises(ValueError):
        normalize(b"date,amount\n2026-09-10,1\n", config)


def test_dates_are_not_coerced_from_compact_or_locale_forms():
    for date in ("20260910", "09/10/2026"):
        result = normalize(f"date,amount\n{date},1\n".encode())
        assert result["events"] == []
        assert result["sources"][0]["payload"] == {}
