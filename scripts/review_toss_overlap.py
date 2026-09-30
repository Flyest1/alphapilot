"""Compare private PDF review tables without mutating or importing account data.

Inputs and outputs may contain account information. Keep all of them under backups/.
This compares observations, not account balances or return accuracy.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict, deque
from decimal import Decimal, InvalidOperation
from pathlib import Path

PARSED_STATUSES = {"needs_source_review", "layout_join_recovered"}
IDENTITY_FIELDS = (
    "date",
    "currency",
    "kind",
    "name_code",
    "quantity",
    "fx_rate",
    "gross_krw",
    "settlement_krw",
    "unit_price_krw",
    "fee_krw",
    "transaction_tax_krw",
    "other_tax_krw",
    "gross_usd",
    "settlement_usd",
    "unit_price_usd",
    "fee_usd",
    "other_tax_usd",
)
NUMERIC_FIELDS = set(IDENTITY_FIELDS) - {"date", "currency", "kind", "name_code"}


def _coordinate(row: dict[str, str]) -> str:
    digest = row.get("source_pdf_sha256", "")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("invalid source PDF digest")
    return f"{digest}:{row.get('page', '')}:{row.get('page_row', '')}"


def _number(value: str) -> str:
    if not value:
        return ""
    try:
        return str(Decimal(value.replace(",", "")).normalize())
    except InvalidOperation as exc:
        raise ValueError("invalid numeric field") from exc


def _strong_key(row: dict[str, str]) -> tuple[str, ...] | None:
    currency = row.get("currency", "")
    suffix = "usd" if currency == "USD" else "krw"
    if (
        row.get("review_status") not in PARSED_STATUSES
        or not row.get("date")
        or not row.get("kind")
        or (row.get("kind") in {"구매", "판매"} and not row.get("name_code"))
        or not row.get("quantity")
        or not row.get(f"gross_{suffix}")
        or not row.get(f"settlement_{suffix}")
    ):
        return None
    return tuple(
        _number(row.get(field, "")) if field in NUMERIC_FIELDS else row.get(field, "").strip()
        for field in IDENTITY_FIELDS
    )


def _weak_key(row: dict[str, str]) -> tuple[str, ...] | None:
    currency = row.get("currency", "")
    if currency not in {"USD", "KRW"}:
        return None
    suffix = "usd" if currency == "USD" else "krw"
    gross = row.get(f"gross_{suffix}", "")
    settled = row.get(f"settlement_{suffix}", "")
    if not all((row.get("date"), row.get("kind"), gross, settled)):
        return None
    return (
        row["date"],
        currency,
        row["kind"],
        _number(gross),
        _number(settled),
    )


def compare_sources(
    baseline: list[dict[str, str]], supplements: list[tuple[str, list[dict[str, str]]]]
) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Classify overlaps; only fully parsed, multiset-matched rows are exact repeats."""
    seen_coordinates: dict[str, dict[str, str]] = {}
    exact: dict[tuple[str, ...], deque[str]] = defaultdict(deque)
    weak: dict[tuple[str, ...], list[str]] = defaultdict(list)
    output: list[dict[str, str]] = []
    counts: Counter[str] = Counter()

    def check(row: dict[str, str]) -> str:
        coordinate = _coordinate(row)
        previous = seen_coordinates.get(coordinate)
        if previous is not None and previous != row:
            raise ValueError("source coordinate has conflicting input")
        seen_coordinates[coordinate] = row
        return coordinate

    def emit(row: dict[str, str], label: str, status: str, matches: list[str]) -> None:
        output.append(
            {
                **row,
                "source_label": label,
                "overlap_status": status,
                "matched_source_rows": ";".join(matches),
            }
        )
        counts[status] += 1

    for row in baseline:
        coordinate = check(row)
        strong = _strong_key(row)
        if strong is not None:
            exact[strong].append(coordinate)
        weak_key = _weak_key(row)
        if weak_key is not None:
            weak[weak_key].append(coordinate)
        emit(row, "baseline", "baseline", [])

    for label, rows in supplements:
        for row in rows:
            coordinate = check(row)
            strong = _strong_key(row)
            if strong is not None and exact[strong]:
                emit(row, label, "duplicate_exact", [exact[strong].popleft()])
                continue
            weak_key = _weak_key(row)
            candidates = weak.get(weak_key, []) if weak_key is not None else []
            if candidates and strong is None:
                status = "overlap_candidate" if len(candidates) == 1 else "overlap_ambiguous"
                emit(row, label, status, candidates)
            elif strong is None:
                emit(row, label, "unresolved", [])
            else:
                emit(row, label, "new_observation", [])
                exact[strong].append(coordinate)
                if weak_key is not None:
                    weak[weak_key].append(coordinate)

    report: dict[str, object] = {
        "observed_row_count": len(output),
        "provisional_distinct_count": len(output) - counts["duplicate_exact"],
        "overlap_counts": dict(counts),
        "coverage_verified": False,
        "ready_for_operating_import": False,
        "account_balance_reconciled": False,
        "returns_validated": False,
    }
    return output, report


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("early", type=Path)
    parser.add_argument("late", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--same-account-confirmed", action="store_true")
    args = parser.parse_args()
    if not args.same_account_confirmed:
        parser.error("manual same-account source check is required")
    root = (Path(__file__).resolve().parent.parent / "backups").resolve()
    output_dir = args.output_dir.resolve()
    if root not in output_dir.parents or output_dir.exists():
        parser.error("output must be a new directory below backups")
    paths = (args.baseline.resolve(), args.early.resolve(), args.late.resolve())
    if any(root not in path.parents for path in paths):
        parser.error("all review tables must be under backups")
    rows, report = compare_sources(
        _read(paths[0]), [("early", _read(paths[1])), ("late", _read(paths[2]))]
    )
    report["input_review_tables"] = [str(path) for path in paths]
    report["same_account_confirmed"] = True
    output_dir.mkdir(parents=True)
    fields = list(rows[0]) if rows else []
    with (output_dir / "overlap_rows.csv").open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(
            {
                key: (
                    "'" + value
                    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@"))
                    else value
                )
                for key, value in row.items()
            }
            for row in rows
        )
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: report[key] for key in ("observed_row_count", "overlap_counts")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
