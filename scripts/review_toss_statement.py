"""Build a source-linked, private review table from locally extracted PDF layout text.

This tool does not parse PDFs, normalize ledger events, or connect to an operating service.
Its JSON input and CSV output contain private account information and must stay under backups/.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

DATE_ROW = re.compile(r"^\s*(20\d{2}\.\d{2}\.\d{2})\s+")
USD_VALUE = re.compile(r"\(\$\s*([0-9,.]+)\)")
SPLIT_CELLS = re.compile(r"\s{2,}")
NUMBER = re.compile(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?\Z")
KRW_BLANK_RATE_KINDS = {
    "구매",
    "판매",
    "분배금",
    "배당금입금",
    "이자입금",
    "외화이자세금출금",
}
KRW_BLANK_RATE_PREFIXES = ("이체입금(", "이체출금(", "오픈뱅킹입금(")
NUMERIC_COLUMNS = {
    "KRW": (
        "fx_rate",
        "quantity",
        "gross_krw",
        "settlement_krw",
        "unit_price_krw",
        "fee_krw",
        "transaction_tax_krw",
        "other_tax_krw",
        "repayment_krw",
        "security_balance",
        "cash_balance_krw",
    ),
    "USD": (
        "fx_rate",
        "quantity",
        "gross_krw",
        "settlement_krw",
        "unit_price_krw",
        "fee_krw",
        "other_tax_krw",
        "repayment_krw",
        "security_balance",
        "cash_balance_krw",
    ),
}
USD_COLUMNS = (
    "gross_usd",
    "settlement_usd",
    "unit_price_usd",
    "fee_usd",
    "other_tax_usd",
    "repayment_usd",
    "cash_balance_usd",
)
CSV_FIELDS = (
    "source_pdf_sha256",
    "page",
    "page_row",
    "currency",
    "date",
    "kind",
    "name_code",
    *NUMERIC_COLUMNS["KRW"],
    *USD_COLUMNS,
    "review_status",
    "raw_first_line",
    "raw_continuation",
)


def parse_layout_pages(pages: list[str], pdf_sha256: str) -> list[dict[str, str | int]]:
    """Keep every date-start row, even when a cell or continuation is uncertain."""
    if not re.fullmatch(r"[0-9a-f]{64}", pdf_sha256):
        raise ValueError("invalid PDF digest")
    rows: list[dict[str, str | int]] = []
    currency: str | None = None
    for page_number, page_text in enumerate(pages, 1):
        current: dict[str, str | int] | None = None
        page_row = 0
        for line in page_text.splitlines():
            normalized = line.replace("\xa0", " ")
            if "원화 거래내역" in normalized:
                currency = "KRW"
            elif "달러 거래내역" in normalized:
                currency = "USD"
            match = DATE_ROW.match(normalized)
            if match:
                page_row += 1
                current = {
                    "source_pdf_sha256": pdf_sha256,
                    "page": page_number,
                    "page_row": page_row,
                    "currency": currency or "UNKNOWN",
                    "date": match.group(1).replace(".", "-"),
                    "raw_first_line": normalized.strip(),
                    "raw_continuation": "",
                }
                rows.append(current)
            elif current is not None and normalized.strip():
                if "거래일자" in normalized or "거래내역" in normalized:
                    current = None
                else:
                    previous = str(current["raw_continuation"])
                    current["raw_continuation"] = (previous + "\n" + normalized.strip()).strip()
    for row in rows:
        _parse_cells(row)
    return rows


def _parse_cells(row: dict[str, str | int]) -> None:
    first_line = str(row["raw_first_line"])
    single_space_recovered = bool(re.search(r"(?<=\d) (?=\d[\d,]*$)", first_line))
    first_line = re.sub(r"(?<=\d) (?=\d[\d,]*$)", "  ", first_line)
    joined_balance = row["currency"] == "KRW" and bool(
        re.search(r"\s0\d{1,3}(?:,\d{3})+$", first_line)
    )
    if joined_balance:
        first_line = re.sub(r"(?<=\s)0(?=\d{1,3}(?:,\d{3})+$)", "0  ", first_line)
    date_text = str(row["date"])
    parts = [date_text] + SPLIT_CELLS.split(first_line[10:].strip())
    row["kind"] = parts[1] if len(parts) > 1 else ""
    row["name_code"] = ""
    currency = str(row["currency"])
    fields = NUMERIC_COLUMNS.get(currency)
    status = "needs_source_review"
    try:
        date.fromisoformat(date_text)
    except ValueError:
        status = "invalid_date"
    if fields is None:
        status = "unknown_currency"
    elif len(parts) >= 2 and status == "needs_source_review":
        remaining = parts[2:]
        has_name = remaining and not re.fullmatch(r"[0-9,.]+", remaining[0])
        numeric = remaining[1:] if has_name else remaining
        if currency == "KRW" and len(numeric) == len(fields) - 1:
            if row["kind"] in KRW_BLANK_RATE_KINDS or str(row["kind"]).startswith(
                KRW_BLANK_RATE_PREFIXES
            ):
                numeric.insert(0, "")
        if len(numeric) == len(fields):
            if has_name:
                row["name_code"] = remaining.pop(0)
            row.update(zip(fields, numeric))
            if any(value and not NUMBER.fullmatch(value) for value in numeric):
                status = "invalid_numeric_cell"
        else:
            status = "cell_count_mismatch"
    else:
        status = "cell_count_mismatch"
    usd_values = USD_VALUE.findall(str(row["raw_continuation"]))
    if currency == "USD":
        if len(usd_values) == len(USD_COLUMNS):
            row.update(zip(USD_COLUMNS, usd_values))
        else:
            status = "usd_continuation_mismatch" if status == "needs_source_review" else status
    if (joined_balance or single_space_recovered) and status == "needs_source_review":
        status = "layout_join_recovered"
    row["review_status"] = status


def summarize_rows(rows: list[dict[str, str | int]]) -> dict[str, object]:
    currency_counts = Counter(str(row["currency"]) for row in rows)
    kind_counts = Counter((str(row["currency"]), str(row["kind"])) for row in rows)
    fx_leg_counts = Counter()
    fx_krw: Counter[tuple[str | Decimal, ...]] = Counter()
    fx_usd: Counter[tuple[str | Decimal, ...]] = Counter()
    fx_unresolved = 0
    costs = Counter()
    cost_parse_errors = 0
    settlement_checks = Counter()
    settlement_unresolved = 0
    for row in rows:
        if row["kind"] == "환전원화출금":
            fx_leg_counts["KRW"] += 1
        elif row["kind"] == "환전외화입금":
            fx_leg_counts["USD"] += 1
        if row["kind"] in ("환전원화출금", "환전외화입금"):
            fields = ("fx_rate", "gross_krw", "settlement_krw")
            if row["review_status"] not in ("needs_source_review", "layout_join_recovered"):
                fx_unresolved += 1
            elif not all(str(row.get(field, "")) for field in fields):
                fx_unresolved += 1
            else:
                try:
                    fx_key = (str(row["date"]),) + tuple(
                        Decimal(str(row[field]).replace(",", "")) for field in fields
                    )
                    (fx_krw if row["kind"] == "환전원화출금" else fx_usd)[fx_key] += 1
                except InvalidOperation:
                    fx_unresolved += 1
        for field in (
            "fee_krw",
            "fee_usd",
            "transaction_tax_krw",
            "other_tax_krw",
            "other_tax_usd",
        ):
            value = str(row.get(field, ""))
            if value:
                try:
                    if Decimal(value.replace(",", "")) != 0:
                        costs[field] += 1
                except InvalidOperation:
                    cost_parse_errors += 1
        if row["kind"] in ("구매", "판매") and row["currency"] in ("KRW", "USD"):
            suffix = "usd" if row["currency"] == "USD" else "krw"
            fields = [
                f"gross_{suffix}",
                f"settlement_{suffix}",
                f"fee_{suffix}",
                f"other_tax_{suffix}",
            ]
            if suffix == "krw":
                fields.append("transaction_tax_krw")
            if not all(str(row.get(field, "")) for field in fields):
                settlement_unresolved += 1
                continue
            try:
                amounts = [Decimal(str(row[field]).replace(",", "")) for field in fields]
            except InvalidOperation:
                settlement_unresolved += 1
                continue
            gross, settled, *cost_values = amounts
            expected = gross + sum(cost_values) * (1 if row["kind"] == "구매" else -1)
            tolerance = Decimal("0.005") if suffix == "usd" else Decimal(0)
            settlement_checks["checked"] += 1
            settlement_checks[
                "matched" if abs(settled - expected) <= tolerance else "mismatched"
            ] += 1
            if abs(settled - expected) > tolerance:
                row["review_status"] = "settlement_mismatch"
    matched = sum((fx_krw & fx_usd).values())
    return {
        "review_status": "requires_source_review",
        "coverage_verified": False,
        "row_count": len(rows),
        "currency_counts": dict(currency_counts),
        "kind_counts": {
            currency: dict(
                Counter({kind: count for (c, kind), count in kind_counts.items() if c == currency})
            )
            for currency in currency_counts
        },
        "fx_leg_counts": dict(fx_leg_counts),
        "fx_unresolved": fx_unresolved,
        "fx_pair_counts": {
            "matched": matched,
            "krw_only": sum(fx_krw.values()) - matched,
            "usd_only": sum(fx_usd.values()) - matched,
        },
        "cost_row_counts": dict(costs),
        "cost_parse_errors": cost_parse_errors,
        "trade_settlement_checks": {
            "checked": settlement_checks["checked"],
            "matched": settlement_checks["matched"],
            "mismatched": settlement_checks["mismatched"],
        },
        "trade_settlement_unresolved": settlement_unresolved,
        "parse_status_counts": dict(Counter(str(row["review_status"]) for row in rows)),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_output_directory(output: Path, backups_root: Path) -> None:
    root = backups_root.resolve()
    target = output.resolve()
    if root not in target.parents or target.exists():
        raise ValueError("output must be a new directory below backups")


def _spreadsheet_safe(row: dict[str, str | int]) -> dict[str, str | int]:
    safe = dict(row)
    for key, value in safe.items():
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "@", "-")):
            safe[key] = "'" + value
    return safe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layout_json", type=Path)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--extractor-name", required=True)
    parser.add_argument("--extractor-version", required=True)
    args = parser.parse_args()
    root = (Path(__file__).resolve().parent.parent / "backups").resolve()
    output = args.output_dir.resolve()
    try:
        validate_output_directory(output, root)
    except ValueError as exc:
        parser.error(str(exc))
    pages = json.loads(args.layout_json.read_text(encoding="utf-8"))
    if not isinstance(pages, list) or not all(isinstance(page, str) for page in pages):
        parser.error("layout JSON must be an array of page text")
    pdf_hash = _sha256(args.pdf)
    rows = parse_layout_pages(pages, pdf_hash)
    report = summarize_rows(rows)
    report.update(
        {
            "pdf_sha256": pdf_hash,
            "layout_json_sha256": _sha256(args.layout_json),
            "extractor_name": args.extractor_name,
            "extractor_version": args.extractor_version,
            "pdf_pages": len(pages),
        }
    )
    output.mkdir(parents=True)
    with (output / "review_rows.csv").open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(_spreadsheet_safe(row) for row in rows)
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps({"row_count": len(rows), "parse_status_counts": report["parse_status_counts"]})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
