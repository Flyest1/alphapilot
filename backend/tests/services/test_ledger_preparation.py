import copy
import hashlib
import json

import pytest

from app.services.ledger.preparation import CHECKS, check_preparation, preparation_template


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def packet(tmp_path):
    def balance(label, cash, day):
        evidence = (label + " synthetic evidence").encode()
        (tmp_path / f"{label}.txt").write_bytes(evidence)
        write_json(
            tmp_path / f"{label}.json",
            {
                "account_id": "local-example",
                "as_of": day,
                "source_record_hash": hashlib.sha256(evidence).hexdigest(),
                "cash_basis": "settled",
                "cash": {"KRW": "0", "USD": cash},
                "receivables": {"KRW": "0", "USD": "0"},
                "payables": {"KRW": "0", "USD": "0"},
                "positions": {},
            },
        )
        return {"balance": f"{label}.json", "evidence": f"{label}.txt"}

    manifest = preparation_template()
    manifest.update(
        account_id="local-example",
        period_start="2026-09-01",
        period_end="2026-09-02",
        observed_at="2026-09-03T10:00:00+09:00",
        opening=balance("opening", "0", "2026-08-31"),
        closing=balance("closing", "10", "2026-09-02"),
        checks=dict.fromkeys(CHECKS, True),
        synthetic=True,
    )
    (tmp_path / "statement.csv").write_bytes(
        b"day,gross,fee,tax,net,memo\n2026-09-01,10,0,0,10,PRIVATE_MEMO\n"
    )
    write_json(
        tmp_path / "mapping.json",
        {
            "version": "statement_csv_v1",
            "columns": {
                "event_date": "day",
                "gross_amount": "gross",
                "fee": "fee",
                "tax": "tax",
                "net_cash_amount": "net",
            },
            "constants": {
                "event_type": "deposit",
                "currency": "USD",
                "timezone": "Asia/Seoul",
                "precision": "date_only",
                "quality": "verified",
            },
        },
    )
    manifest["statements"] = [
        {
            "csv": "statement.csv",
            "mapping": "mapping.json",
            "period_start": "2026-09-01",
            "period_end": "2026-09-02",
        }
    ]
    write_json(tmp_path / "manifest.json", manifest)
    return manifest


def run(tmp_path, manifest):
    write_json(tmp_path / "manifest.json", manifest)
    return check_preparation(tmp_path / "manifest.json")


def codes(result):
    return {item["code"] for item in result["blockers"]}


def test_empty_template_reports_missing_material_without_inventing_balances(tmp_path):
    result = run(tmp_path, preparation_template())
    assert result["status"] == "blocked"
    assert {"missing_account", "missing_period", "missing_opening", "missing_closing"} <= codes(
        result
    )
    assert result["reconciliation"] is None
    assert result["coverage_verified"] is False


def test_matching_synthetic_packet_is_only_ready_for_review_and_preserves_sources(tmp_path):
    manifest = packet(tmp_path)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    result = run(tmp_path, manifest)
    assert result["status"] == "ready_for_review"
    assert result["reconciliation"]["status"] == "matched"
    assert result["coverage_verified"] is False
    assert result["return_rate"] is None and result["realized_profit_loss"] is None
    assert result["synthetic"] is True
    assert result["stored"] is False
    assert "PRIVATE_MEMO" not in json.dumps(result)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


@pytest.mark.parametrize("problem", ["wrong_account", "wrong_date", "wrong_hash", "buying_power"])
def test_invalid_balance_evidence_blocks_readiness(tmp_path, problem):
    manifest = packet(tmp_path)
    path = tmp_path / "closing.json"
    value = json.loads(path.read_text())
    field, replacement = {
        "wrong_account": ("account_id", "other"),
        "wrong_date": ("as_of", "2026-09-01"),
        "wrong_hash": ("source_record_hash", "0" * 64),
        "buying_power": ("cash_basis", "buying_power"),
    }[problem]
    value[field] = replacement
    write_json(path, value)
    assert run(tmp_path, manifest)["status"] == "blocked"


def test_balance_mismatch_is_reported_without_rounding_or_claiming_profit(tmp_path):
    manifest = packet(tmp_path)
    path = tmp_path / "closing.json"
    value = json.loads(path.read_text())
    value["cash"]["USD"] = "10.000000000001"
    write_json(path, value)
    result = run(tmp_path, manifest)
    assert "balance_mismatch" in codes(result)
    assert result["reconciliation"]["residuals"]["cash"]["USD"] == "0.000000000001"


def test_declared_period_gap_blocks_even_when_balances_match(tmp_path):
    manifest = packet(tmp_path)
    manifest["statements"][0]["period_end"] = "2026-09-01"
    assert "statement_period_gap" in codes(run(tmp_path, manifest))


def test_partial_rows_remain_blocked_with_matching_valid_subset(tmp_path):
    manifest = packet(tmp_path)
    with (tmp_path / "statement.csv").open("ab") as stream:
        stream.write(b"bad-date,1,0,0,1,PRIVATE_MEMO\n")
    result = run(tmp_path, manifest)
    assert "invalid_statement_rows" in codes(result)
    assert result["documents"][0]["errors"][0]["row"] == 2
    assert "PRIVATE_MEMO" not in json.dumps(result)


def test_repeated_document_and_economic_duplicates_are_not_silently_accepted(tmp_path):
    manifest = packet(tmp_path)
    second = copy.deepcopy(manifest["statements"][0])
    manifest["statements"].append(second)
    assert "repeated_document" in codes(run(tmp_path, manifest))
    second["csv"] = "overlap.csv"
    (tmp_path / "overlap.csv").write_bytes(
        b"day,gross,fee,tax,net,memo\n2026-09-01,10,0,0,10,different memo\n"
    )
    result = run(tmp_path, manifest)
    assert "review_issues" in codes(result)
    assert result["duplicate_candidates"] == 1


@pytest.mark.parametrize("problem", ["unchecked", "provisional", "outside_period", "future"])
def test_unreviewed_or_out_of_scope_material_is_blocked(tmp_path, problem):
    manifest = packet(tmp_path)
    if problem == "unchecked":
        manifest["checks"][CHECKS[0]] = False
    elif problem == "provisional":
        mapping = json.loads((tmp_path / "mapping.json").read_text())
        mapping["constants"].pop("quality")
        write_json(tmp_path / "mapping.json", mapping)
    elif problem == "outside_period":
        (tmp_path / "statement.csv").write_bytes(
            b"day,gross,fee,tax,net,memo\n2026-08-31,10,0,0,10,private\n"
        )
    else:
        manifest["observed_at"] = "2026-09-01T10:00:00+09:00"
    assert run(tmp_path, manifest)["status"] == "blocked"


def test_input_escape_and_unknown_fields_are_rejected_without_echoing_values(tmp_path):
    manifest = packet(tmp_path)
    manifest["statements"][0]["csv"] = "../PRIVATE_SECRET.csv"
    result = run(tmp_path, manifest)
    assert result["status"] == "blocked"
    assert "PRIVATE_SECRET" not in json.dumps(result)
    manifest["unexpected"] = "PRIVATE_SECRET"
    result = run(tmp_path, manifest)
    assert "invalid_manifest" in codes(result)
    assert "PRIVATE_SECRET" not in json.dumps(result)


def test_invalid_rows_across_documents_share_the_total_row_budget(tmp_path, monkeypatch):
    from app.services.ledger import preparation

    manifest = packet(tmp_path)
    monkeypatch.setattr(preparation, "MAX_ROWS", 1)
    (tmp_path / "statement.csv").write_bytes(b"day,gross,fee,tax,net\nbad,1,0,0,1\n")
    second = copy.deepcopy(manifest["statements"][0])
    second["csv"] = "second.csv"
    (tmp_path / "second.csv").write_bytes(b"day,gross,fee,tax,net\n2026-09-01,1,0,0,1\n")
    manifest["statements"].append(second)
    result = run(tmp_path, manifest)
    assert {"code": "invalid_statement", "document": 2} in result["blockers"]


def test_markdown_report_explains_matched_does_not_verify_coverage(tmp_path):
    from app.services.ledger.preparation_report import render_preparation_report

    result = run(tmp_path, packet(tmp_path))
    text = render_preparation_report(result)
    assert "검토 가능" in text and "숫자 일치" in text
    assert "완전성을 인정하지 않습니다" in text
    assert "PRIVATE_MEMO" not in text
    assert "local-example" not in text
