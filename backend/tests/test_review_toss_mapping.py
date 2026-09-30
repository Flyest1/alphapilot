import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "review_toss_mapping.py"
SPEC = importlib.util.spec_from_file_location("review_toss_mapping", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def row(digest, number, date, overlap, *, review="needs_source_review"):
    return {
        "source_pdf_sha256": digest * 64,
        "page": "1",
        "page_row": str(number),
        "date": date,
        "currency": "USD",
        "kind": "구매",
        "name_code": "예시(TEST)",
        "review_status": review,
        "overlap_status": overlap,
        "matched_source_rows": "",
    }


def test_plan_preserves_all_observations_but_excludes_overlaps_and_earlier_period():
    baseline = row("a", 1, "2026-06-01", "baseline")
    earlier = row("b", 1, "2026-05-29", "new_observation")
    duplicate = row("c", 1, "2026-06-01", "duplicate_exact")
    later = row("d", 1, "2026-09-30", "new_observation")
    candidate = row("e", 1, "2026-09-28", "overlap_candidate", review="cell_count_mismatch")
    candidate["matched_source_rows"] = MODULE.coordinate(baseline)
    decisions = [
        {
            "source_row": MODULE.coordinate(candidate),
            "matched_source_row": MODULE.coordinate(baseline),
            "basis": "visual_same_pdf_row",
        }
    ]

    inventory, report = MODULE.plan_mapping(
        [baseline, earlier, duplicate, later, candidate], decisions, "2026-06-01", "2026-09-30"
    )

    assert len(inventory) == 5
    assert report["counts"] == {
        "in_period_mapping_blocked": 2,
        "outside_period": 1,
        "duplicate_exact": 1,
        "duplicate_manual_visual": 1,
    }
    assert report["in_period_observations"] == 2
    assert report["coverage_verified"] is False
    assert report["ready_for_operating_import"] is False
    assert inventory[3]["event_date_candidate"] == "2026-09-30"
    assert inventory[3]["event_date_confirmed"] == "false"


def test_unreviewed_overlap_candidate_is_held_not_imported():
    candidate = row("a", 1, "2026-09-28", "overlap_candidate")
    candidate["matched_source_rows"] = "b" * 64 + ":1:1"

    inventory, report = MODULE.plan_mapping([candidate], [], "2026-06-01", "2026-09-30")

    assert inventory[0]["mapping_status"] == "overlap_unresolved"
    assert report["in_period_observations"] == 0


def test_manual_duplicate_must_reference_reported_candidate_and_known_source():
    candidate = row("a", 1, "2026-09-28", "overlap_candidate")
    candidate["matched_source_rows"] = "b" * 64 + ":1:1"
    invalid = [
        {
            "source_row": MODULE.coordinate(candidate),
            "matched_source_row": "c" * 64 + ":1:1",
            "basis": "visual_same_pdf_row",
        }
    ]

    with pytest.raises(ValueError, match="decision"):
        MODULE.plan_mapping([candidate], invalid, "2026-06-01", "2026-09-30")


def test_layout_recovery_stays_provisional_after_inventory():
    recovered = row("a", 1, "2026-06-01", "baseline", review="layout_join_recovered")

    inventory, _ = MODULE.plan_mapping([recovered], [], "2026-06-01", "2026-09-30")

    assert inventory[0]["mapping_status"] == "in_period_mapping_blocked"
    assert inventory[0]["source_review_status"] == "layout_join_recovered"
    assert "layout_source_review" in inventory[0]["blocking_reasons"]
