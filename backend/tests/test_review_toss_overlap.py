import csv
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "review_toss_overlap.py"
SPEC = importlib.util.spec_from_file_location("review_toss_overlap", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def row(digest, page_row, *, date="2026-09-28", quantity="1", status="needs_source_review"):
    return {
        "source_pdf_sha256": digest * 64,
        "page": "1",
        "page_row": str(page_row),
        "currency": "USD",
        "date": date,
        "kind": "구매",
        "name_code": "예시(TEST)",
        "quantity": quantity,
        "gross_usd": "1.00",
        "settlement_usd": "1.00",
        "fee_usd": "0.00",
        "other_tax_usd": "0.00",
        "review_status": status,
    }


def test_exact_overlap_is_multiset_and_keeps_both_source_rows():
    base = [row("a", 1), row("a", 2)]
    supplement = [row("b", 1), row("b", 2), row("b", 3)]

    results, report = MODULE.compare_sources(base, [("boundary", supplement)])

    assert [item["overlap_status"] for item in results] == [
        "baseline",
        "baseline",
        "duplicate_exact",
        "duplicate_exact",
        "new_observation",
    ]
    assert report["overlap_counts"] == {
        "baseline": 2,
        "duplicate_exact": 2,
        "new_observation": 1,
    }
    assert results[2]["matched_source_rows"] == "a" * 64 + ":1:1"
    assert report["coverage_verified"] is False
    assert report["ready_for_operating_import"] is False


def test_each_later_document_reuses_prior_multiset_without_consuming_it():
    results, report = MODULE.compare_sources(
        [row("a", 1), row("a", 2)],
        [
            ("early", [row("b", 1), row("b", 2), row("b", 3)]),
            ("late", [row("c", 1), row("c", 2), row("c", 3)]),
            ("latest", [row("d", 1), row("d", 2)]),
        ],
    )

    assert [item["overlap_status"] for item in results] == [
        "baseline",
        "baseline",
        "duplicate_exact",
        "duplicate_exact",
        "new_observation",
        "duplicate_exact",
        "duplicate_exact",
        "duplicate_exact",
        "duplicate_exact",
        "duplicate_exact",
    ]
    assert [item["matched_source_rows"] for item in results[5:]] == [
        "a" * 64 + ":1:1",
        "a" * 64 + ":1:2",
        "b" * 64 + ":1:3",
        "a" * 64 + ":1:1",
        "a" * 64 + ":1:2",
    ]
    assert report["provisional_distinct_count"] == 3
    assert report["coverage_verified"] is False


def test_unparsed_row_is_only_candidate_not_auto_deduplicated():
    base = [row("a", 1)]
    broken = row("b", 1, status="cell_count_mismatch")
    broken["name_code"] = ""
    broken["quantity"] = ""

    results, report = MODULE.compare_sources(base, [("boundary", [broken])])

    assert results[1]["overlap_status"] == "overlap_candidate"
    assert results[1]["matched_source_rows"] == "a" * 64 + ":1:1"
    assert report["provisional_distinct_count"] == 2


def test_ambiguous_weak_match_does_not_claim_duplicate():
    base = [row("a", 1), row("a", 2, quantity="2")]
    broken = row("b", 1, status="cell_count_mismatch")
    broken["name_code"] = ""
    broken["quantity"] = ""

    results, _ = MODULE.compare_sources(base, [("boundary", [broken])])

    assert results[-1]["overlap_status"] == "overlap_ambiguous"
    assert len(results[-1]["matched_source_rows"].split(";")) == 2


def test_new_date_does_not_require_future_statement():
    results, report = MODULE.compare_sources(
        [row("a", 1)], [("boundary", [row("b", 1, date="2026-09-30")])]
    )

    assert results[-1]["overlap_status"] == "new_observation"
    assert report["observed_row_count"] == 2


def test_parsed_cash_event_without_security_name_can_match_exactly():
    base = row("a", 1)
    boundary = row("b", 1)
    for item in (base, boundary):
        item["kind"] = "환전원화출금"
        item["currency"] = "KRW"
        item["name_code"] = ""
        item["quantity"] = "0"
        item["gross_krw"] = "1,000"
        item["settlement_krw"] = "1,000"

    results, _ = MODULE.compare_sources([base], [("boundary", [boundary])])

    assert results[-1]["overlap_status"] == "duplicate_exact"


def test_rejects_same_source_digest_with_conflicting_input():
    base = [row("a", 1)]
    changed = row("a", 1, quantity="2")

    try:
        MODULE.compare_sources(base, [("boundary", [changed])])
    except ValueError as exc:
        assert "source coordinate" in str(exc)
    else:
        raise AssertionError("conflicting source coordinate was accepted")


def test_rejects_repeated_source_coordinate_even_with_identical_input():
    repeated = row("a", 1)

    with pytest.raises(ValueError, match="source coordinate"):
        MODULE.compare_sources([repeated], [("boundary", [repeated.copy()])])


def test_cli_compares_four_review_tables_without_overwriting_input(tmp_path, monkeypatch):
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    sources = []
    for digest in "abcd":
        path = backup_root / f"{digest}.csv"
        with path.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=list(row(digest, 1)))
            writer.writeheader()
            writer.writerow(row(digest, 1))
        sources.append(path)
    original_bytes = [path.read_bytes() for path in sources]
    output = backup_root / "review"
    monkeypatch.setattr(MODULE, "__file__", str(tmp_path / "scripts" / "review_toss_overlap.py"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "review_toss_overlap.py",
            *(str(path) for path in sources),
            "--output-dir",
            str(output),
            "--same-account-confirmed",
        ],
    )

    assert MODULE.main() == 0

    with (output / "overlap_rows.csv").open(encoding="utf-8-sig", newline="") as source:
        results = list(csv.DictReader(source))
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert [item["overlap_status"] for item in results] == [
        "baseline",
        "duplicate_exact",
        "duplicate_exact",
        "duplicate_exact",
    ]
    assert [item["source_label"] for item in results] == [
        "baseline",
        "early",
        "late",
        "supplement_3",
    ]
    assert report["provisional_distinct_count"] == 1
    assert report["ready_for_operating_import"] is False
    assert [path.read_bytes() for path in sources] == original_bytes
