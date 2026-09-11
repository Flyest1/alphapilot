"""Offline price-snapshot comparison, without adjustment or outcome rewriting."""

from datetime import date
from math import isclose, isfinite
from typing import Any

FIELDS = ("open", "high", "low", "close")


def _rows_by_date(rows: list[dict], start: date, end: date) -> dict:
    result = {}
    for row in rows:
        day = date.fromisoformat(row["date"][:10])
        if not start <= day <= end:
            continue
        if day in result:
            raise ValueError("Duplicate session")
        numbers = {}
        for key in (*FIELDS, "dividend", "split"):
            value = row.get(key, 0 if key in {"dividend", "split"} else None)
            if isinstance(value, bool) or value is None:
                raise ValueError("Missing or invalid price")
            value = float(value)
            if not isfinite(value) or value < 0 or (key in FIELDS and value == 0):
                raise ValueError("Nonfinite or nonpositive price")
            numbers[key] = value
        if not (
            numbers["low"]
            <= min(numbers["open"], numbers["close"])
            <= max(numbers["open"], numbers["close"])
            <= numbers["high"]
        ):
            raise ValueError("Incoherent OHLC")
        result[day] = numbers
    return result


def compare_price_evidence(
    archived: list[dict[str, Any]], refreshed: list[dict[str, Any]], *, start: str, end: str
) -> dict[str, Any]:
    lower, upper = date.fromisoformat(start), date.fromisoformat(end)
    if lower > upper:
        raise ValueError("start must be on or before end")
    result = {
        "policy_version": "price_revision_diagnostic_v1",
        "research_only": True,
        "price_basis_verified": False,
        "start": start,
        "end": end,
        "relative_tolerance": 1e-6,
        "absolute_tolerance": 1e-6,
    }
    try:
        old = _rows_by_date(archived, lower, upper)
        new = _rows_by_date(refreshed, lower, upper)
    except (ValueError, TypeError, KeyError, OverflowError):
        return {**result, "status": "invalid_input"}
    revisions = []
    for day in sorted(old.keys() & new.keys()):
        changed = [
            key
            for key in FIELDS
            if not isclose(old[day][key], new[day][key], rel_tol=1e-6, abs_tol=1e-6)
        ]
        if changed:
            revisions.append(
                {
                    "date": day.isoformat(),
                    "changed_fields": changed,
                    "archived": {key: old[day][key] for key in FIELDS},
                    "refreshed": {key: new[day][key] for key in FIELDS},
                    "close_change_pct": round((new[day]["close"] / old[day]["close"] - 1) * 100, 6),
                }
            )
    return {
        **result,
        "status": "compared" if old.keys() & new.keys() else "no_overlap",
        "matched_session_count": len(old.keys() & new.keys()),
        "revised_close_count": sum("close" in row["changed_fields"] for row in revisions),
        "missing_in_refreshed": [day.isoformat() for day in sorted(old.keys() - new.keys())],
        "missing_in_archived": [day.isoformat() for day in sorted(new.keys() - old.keys())],
        "revisions": revisions,
        "corporate_actions": [
            {"date": day.isoformat(), "split": row["split"], "dividend": row["dividend"]}
            for day, row in sorted(new.items())
            if row["split"] or row["dividend"]
        ],
        "limitations": [
            "Matching snapshots do not prove compatibility with original recommendation prices.",
            "Revisions may reflect incomplete bars, corrections or adjustments; cause is unknown.",
            "Missing action fields mean unknown coverage, not confirmed absence of actions.",
            "No currency conversion, dividend reinvestment or retrospective barrier adjustment.",
        ],
    }
