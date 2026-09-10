from copy import deepcopy

import pandas as pd
import pytest

from app.services.measurement_audit import audit_recommendations


def test_audit_uses_original_barriers_even_if_superseded_and_does_not_mutate():
    original = {
        "ticker": "AAPL",
        "action": "BUY",
        "horizon": "short",
        "decision_at": "2026-01-01T00:00:00+00:00",
        "reference_price": 100,
        "target_price": 110,
        "stop_loss": 90,
    }
    cycle = {
        "id": "a",
        "status": "superseded",
        "target_price": 120,
        "metadata": {"original_decision": original},
    }
    before = deepcopy(cycle)
    frame = pd.DataFrame(
        {"close": [100, 111], "high": [100, 111], "low": [100, 99]},
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )
    result = audit_recommendations([cycle], {"AAPL": frame}, as_of="2026-01-05")
    assert result["observations"][0]["status"] == "hit_target"
    assert result["observations"][0]["stored_status"] == "superseded"
    assert result["changed_status_count"] == 1
    assert cycle == before


def test_audit_classifies_unrecoverable_original_and_missing_price_anchor():
    cycles = [
        {"id": "legacy", "metadata": {}},
        {
            "id": "late",
            "metadata": {
                "original_decision": {
                    "ticker": "AAPL",
                    "action": "BUY",
                    "horizon": "short",
                    "decision_at": "2026-01-01",
                    "reference_price": 100,
                    "target_price": 110,
                    "stop_loss": 90,
                }
            },
        },
    ]
    frame = pd.DataFrame({"close": [120]}, index=pd.to_datetime(["2026-01-05"]))
    result = audit_recommendations(cycles, {"AAPL": frame}, as_of="2026-01-06")
    assert result["excluded_reasons"] == {
        "missing_original_decision": 1,
        "missing_history_anchor": 1,
    }
    assert result["evaluated_count"] == 0


def test_audit_does_not_use_price_after_as_of():
    cycle = {
        "id": "a",
        "metadata": {
            "original_decision": {
                "ticker": "AAPL",
                "action": "BUY",
                "horizon": "short",
                "decision_at": "2026-01-01",
                "reference_price": 100,
                "target_price": 110,
                "stop_loss": 90,
            }
        },
    }
    frame = pd.DataFrame({"close": [100, 120]}, index=pd.to_datetime(["2026-01-01", "2026-01-05"]))
    result = audit_recommendations([cycle], {"AAPL": frame}, as_of="2026-01-02")
    assert result["observations"][0]["status"] == "pending"


@pytest.mark.parametrize(
    "rows,reason",
    [
        ({"close": [100, 105]}, "missing_barrier_prices"),
        ({"close": [100, 105], "high": [100, 101], "low": [100, 104]}, "invalid_price_history"),
    ],
)
def test_audit_rejects_incomplete_or_incoherent_barrier_prices(rows, reason):
    cycle = {
        "id": "a",
        "metadata": {
            "original_decision": {
                "ticker": "AAPL",
                "action": "BUY",
                "horizon": "short",
                "decision_at": "2026-01-01",
                "reference_price": 100,
                "target_price": 110,
                "stop_loss": 90,
            }
        },
    }
    frame = pd.DataFrame(rows, index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
    result = audit_recommendations([cycle], {"AAPL": frame}, as_of="2026-01-05")
    assert result["excluded_reasons"] == {reason: 1}


def test_bad_metadata_does_not_abort_other_audit_rows():
    result = audit_recommendations(
        [{"id": "broken", "metadata": [1]}, {"id": "legacy"}], {}, as_of="2026-01-05"
    )
    assert result["sample_count"] == 2
    assert result["evaluated_count"] == 0


@pytest.mark.parametrize("bad_geometry", [False, True])
def test_duplicate_daily_bars_and_inverted_barriers_are_excluded(bad_geometry):
    cycle = {
        "id": "a",
        "metadata": {
            "original_decision": {
                "ticker": "AAPL",
                "action": "SELL",
                "horizon": "short",
                "decision_at": "2026-01-01",
                "reference_price": 100,
                "target_price": 110 if bad_geometry else 90,
                "stop_loss": 110,
            }
        },
    }
    dates = ["2026-01-01", "2026-01-02T09:00", "2026-01-02T14:00"]
    if bad_geometry:
        dates[-1] = "2026-01-05"
    frame = pd.DataFrame(
        {"close": [100] * 3, "high": [101] * 3, "low": [99] * 3}, index=pd.DatetimeIndex(dates)
    )
    result = audit_recommendations([cycle], {"AAPL": frame}, as_of="2026-01-06")
    reason = "invalid_original_barriers" if bad_geometry else "duplicate_price_sessions"
    assert result["excluded_reasons"] == {reason: 1}
