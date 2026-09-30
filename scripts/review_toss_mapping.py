"""Build a private, fail-closed mapping inventory from PDF overlap observations.

This is not a statement CSV adapter. It does not create LedgerEvent rows, infer
settlement dates, certify source quality, or connect to an operating service.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import date
from pathlib import Path


def coordinate(row: dict[str, str]) -> str:
    digest = row.get("source_pdf_sha256", "")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("invalid source PDF digest")
    page = row.get("page", "")
    page_row = row.get("page_row", "")
    if not page.isdecimal() or not page_row.isdecimal():
        raise ValueError("invalid source coordinate")
    return f"{digest}:{page}:{page_row}"


def plan_mapping(
    rows: list[dict[str, str]],
    decisions: list[dict[str, str]],
    period_start: str,
    period_end: str,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Retain every observation; select a period without creating importable events."""
    start, end = date.fromisoformat(period_start), date.fromisoformat(period_end)
    if start > end:
        raise ValueError("reversed review period")
    by_coordinate: dict[str, dict[str, str]] = {}
    for row in rows:
        key = coordinate(row)
        if key in by_coordinate:
            raise ValueError("repeated source coordinate")
        by_coordinate[key] = row
    reviewed: set[str] = set()
    for decision in decisions:
        if not isinstance(decision, dict) or set(decision) != {
            "source_row",
            "matched_source_row",
            "basis",
        }:
            raise ValueError("invalid manual decision")
        source_row = decision["source_row"]
        matched = decision["matched_source_row"]
        source = by_coordinate.get(source_row)
        if (
            source_row in reviewed
            or source is None
            or matched not in by_coordinate
            or source.get("overlap_status") != "overlap_candidate"
            or matched not in source.get("matched_source_rows", "").split(";")
            or decision["basis"] != "visual_same_pdf_row"
        ):
            raise ValueError("manual decision does not match overlap evidence")
        reviewed.add(source_row)

    counts: Counter[str] = Counter()
    inventory: list[dict[str, str]] = []
    for row in rows:
        source_day = date.fromisoformat(row["date"])
        overlap = row.get("overlap_status")
        if overlap == "duplicate_exact":
            status = "duplicate_exact"
        elif overlap == "overlap_candidate" and coordinate(row) in reviewed:
            status = "duplicate_manual_visual"
        elif overlap in {"overlap_candidate", "overlap_ambiguous", "unresolved"}:
            status = "overlap_unresolved"
        elif overlap not in {"baseline", "new_observation"}:
            raise ValueError("unknown overlap status")
        elif not start <= source_day <= end:
            status = "outside_period"
        else:
            status = "in_period_mapping_blocked"
        counts[status] += 1
        reasons = []
        if status == "in_period_mapping_blocked":
            reasons = [
                "source_review",
                "event_date_basis_unconfirmed",
                "event_type_mapping_unconfirmed",
            ]
            if row.get("kind") in {"구매", "판매"}:
                reasons += ["symbol_mapping_unconfirmed", "settlement_date_unconfirmed"]
            if row.get("review_status") == "layout_join_recovered":
                reasons.append("layout_source_review")
        inventory.append(
            {
                **row,
                "mapping_status": status,
                "source_review_status": row.get("review_status", ""),
                "event_date_candidate": (
                    row["date"] if status == "in_period_mapping_blocked" else ""
                ),
                "event_date_confirmed": "false",
                "blocking_reasons": ";".join(reasons),
            }
        )
    report: dict[str, object] = {
        "period_start": period_start,
        "period_end": period_end,
        "observed_row_count": len(rows),
        "in_period_observations": counts["in_period_mapping_blocked"],
        "counts": dict(counts),
        "manual_visual_duplicate_count": len(reviewed),
        "coverage_verified": False,
        "ready_for_operating_import": False,
        "account_balance_reconciled": False,
        "returns_validated": False,
        "statement_csv_created": False,
    }
    return inventory, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("overlap_csv", type=Path)
    parser.add_argument("decisions_json", type=Path)
    parser.add_argument("--period-start", required=True)
    parser.add_argument("--period-end", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    root = (Path(__file__).resolve().parent.parent / "backups").resolve()
    paths = (args.overlap_csv.resolve(), args.decisions_json.resolve())
    output = args.output_dir.resolve()
    if (
        any(root not in path.parents for path in paths)
        or root not in output.parents
        or output.exists()
    ):
        parser.error("inputs and new output directory must be below backups")
    with paths[0].open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    decisions = json.loads(paths[1].read_text(encoding="utf-8"))
    if not isinstance(decisions, list):
        parser.error("decisions must be an array")
    inventory, report = plan_mapping(rows, decisions, args.period_start, args.period_end)
    output.mkdir(parents=True)
    fields = list(inventory[0]) if inventory else []
    with (output / "mapping_inventory.csv").open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
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
            for row in inventory
        )
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"counts": report["counts"], "stored": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
