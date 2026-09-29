import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "review_toss_statement.py"
SPEC = importlib.util.spec_from_file_location("review_toss_statement", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
_spreadsheet_safe = MODULE._spreadsheet_safe
parse_layout_pages = MODULE.parse_layout_pages
summarize_rows = MODULE.summarize_rows
validate_output_directory = MODULE.validate_output_directory


def test_parse_layout_preserves_section_transition_and_source_coordinates():
    pages = [
        "원화 거래내역\n거래일자 거래구분\n"
        "2024.04.30  판매  예시(A000001)  1  1  200  189  200  1  2  8  0  0  1,000\n"
        "달러 거래내역\n거래일자 거래구분\n"
        "2024.04.01  구매  테스트(US0000000001)  1,200  "
        "0.5  600  612  1,200  12  0  0  1.5  2,400\n"
        "($ 0.50)  ($ 0.51)  ($ 1.00)  ($ 0.01)  ($ 0.00)  "
        "($ 0.00)  ($ 2.00)"
    ]

    rows = parse_layout_pages(pages, "a" * 64)

    assert [(row["currency"], row["page"], row["page_row"]) for row in rows] == [
        ("KRW", 1, 1),
        ("USD", 1, 2),
    ]
    assert rows[1]["name_code"] == "테스트(US0000000001)"
    assert rows[1]["gross_usd"] == "0.50"
    assert rows[1]["settlement_usd"] == "0.51"
    assert rows[0]["other_tax_krw"] == "8"


def test_parse_layout_flags_unexpected_cell_count_without_dropping_row():
    rows = parse_layout_pages(["원화 거래내역\n2024.04.01  구매  broken"], "b" * 64)

    assert len(rows) == 1
    assert rows[0]["review_status"] == "cell_count_mismatch"
    assert rows[0]["raw_first_line"].startswith("2024.04.01")


def test_parse_layout_keeps_adjacent_holdings_and_cash_separate():
    line = (
        "원화 거래내역\n2024.04.01  구매  예시(A000001)  1  200  200  " "200  0  0  0  0  1 1,000"
    )

    row = parse_layout_pages([line], "d" * 64)[0]

    assert row["quantity"] == "1"
    assert row["security_balance"] == "1"
    assert row["cash_balance_krw"] == "1,000"
    assert row["fx_rate"] == ""
    assert row["review_status"] == "layout_join_recovered"


def test_parse_layout_flags_joined_zero_holdings_as_recovered_not_verified():
    line = "원화 거래내역\n2024.04.02  판매  예시(A000001)  1  200  189  " "200  1  2  8  0  01,000"

    row = parse_layout_pages([line], "e" * 64)[0]

    assert row["security_balance"] == "0"
    assert row["cash_balance_krw"] == "1,000"
    assert row["review_status"] == "layout_join_recovered"


def test_parse_layout_recovers_joined_zero_with_million_cash_balance():
    line = (
        "원화 거래내역\n2024.04.03  판매  예시(A000001)  9  2,000,000  "
        "1,999,000  200,000  100  200  700  0  02,000,000"
    )

    row = parse_layout_pages([line], "f" * 64)[0]

    assert row["security_balance"] == "0"
    assert row["cash_balance_krw"] == "2,000,000"


def test_summary_counts_fx_legs_and_nonzero_costs_without_claiming_coverage():
    pages = [
        "원화 거래내역\n"
        "2024.04.01  환전원화출금  1,200.00  0  12,000  12,000  0  0  0  0  0  0  50,000\n"
        "달러 거래내역\n"
        "2024.04.02  환전외화입금  1,200.00  0  12,000  12,000  0  0  0  0  0  1,000\n"
        "($ 10.00)  ($ 10.00)  ($ 0.00)  ($ 0.00)  ($ 0.00)  ($ 0.00)  ($ 1,000.00)"
    ]

    report = summarize_rows(parse_layout_pages(pages, "c" * 64))

    assert report["coverage_verified"] is False
    assert report["currency_counts"] == {"KRW": 1, "USD": 1}
    assert report["fx_leg_counts"] == {"KRW": 1, "USD": 1}
    assert report["fx_pair_counts"] == {"matched": 0, "krw_only": 1, "usd_only": 1}
    assert report["review_status"] == "requires_source_review"
    assert json.dumps(report)


def test_summary_pairs_duplicate_fx_legs_as_multisets_and_counts_costs():
    pages = [
        "원화 거래내역\n"
        "2024.04.01  환전원화출금  1,200  0  12,000  12,000  0  0  0  0  0  0  50,000\n"
        "2024.04.01  환전원화출금  1,200  0  12,000  12,000  0  0  0  0  0  0  38,000\n"
        "달러 거래내역\n"
        "2024.04.01  환전외화입금  1,200  0  12,000  12,000  0  0  0  0  0  1,000\n"
        "($ 10.00)  ($ 10.00)  ($ 0.00)  ($ 0.00)  ($ 0.00)  ($ 0.00)  ($ 1,000.00)\n"
        "2024.04.02  구매  예시(US0000000001)  1,200  1  12,000  12,024  "
        "12,000  24  0  0  1  900\n"
        "($ 10.00)  ($ 10.02)  ($ 10.00)  ($ 0.02)  ($ 0.00)  ($ 0.00)  ($ 900.00)"
    ]

    report = summarize_rows(parse_layout_pages(pages, "1" * 64))

    assert report["fx_pair_counts"] == {"matched": 1, "krw_only": 1, "usd_only": 0}
    assert report["cost_row_counts"]["fee_usd"] == 1
    assert report["trade_settlement_checks"] == {"checked": 1, "matched": 1, "mismatched": 0}


def test_summary_does_not_hide_trade_settlement_mismatch():
    pages = [
        "원화 거래내역\n2024.04.03  판매  예시(A000001)  1  200  " "180  200  1  2  8  0  0  1,000"
    ]

    rows = parse_layout_pages(pages, "2" * 64)
    report = summarize_rows(rows)

    assert report["trade_settlement_checks"] == {"checked": 1, "matched": 0, "mismatched": 1}
    assert rows[0]["review_status"] == "settlement_mismatch"


def test_fx_pairing_rejects_unparsed_rows_even_when_dates_match():
    pages = [
        "원화 거래내역\n2024.04.01  환전원화출금  broken\n"
        "달러 거래내역\n2024.04.01  환전외화입금  broken"
    ]

    report = summarize_rows(parse_layout_pages(pages, "3" * 64))

    assert report["fx_pair_counts"]["matched"] == 0
    assert report["fx_unresolved"] == 2


def test_fx_row_never_infers_a_missing_exchange_rate():
    page = "원화 거래내역\n2024.04.01  환전원화출금  0  12,000  12,000  " "0  0  0  0  0  0  50,000"

    row = parse_layout_pages([page], "4" * 64)[0]

    assert row["review_status"] == "cell_count_mismatch"


def test_open_banking_deposit_can_have_blank_exchange_rate():
    page = (
        "원화 거래내역\n2024.04.01  오픈뱅킹입금(테스트)  0  100  100  " "0  0  0  0  0  0  1,000"
    )

    row = parse_layout_pages([page], "5" * 64)[0]

    assert row["fx_rate"] == ""
    assert row["settlement_krw"] == "100"


def test_output_directory_must_be_new_child_of_backups(tmp_path):
    root = tmp_path / "backups"
    root.mkdir()
    validate_output_directory(root / "new", root)
    for invalid in (root, tmp_path / "outside", root / ".." / "escape"):
        with pytest.raises(ValueError):
            validate_output_directory(invalid, root)
    existing = root / "existing"
    existing.mkdir()
    with pytest.raises(ValueError):
        validate_output_directory(existing, root)


def test_spreadsheet_export_escapes_formula_cells_without_changing_source_row():
    row = {"name_code": '=HYPERLINK("example")', "raw_first_line": "2024.04.01 test"}

    safe = _spreadsheet_safe(row)

    assert safe["name_code"].startswith("'=")
    assert row["name_code"].startswith("=")
