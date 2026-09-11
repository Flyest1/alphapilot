from copy import deepcopy

import pandas as pd
import pytest

from app.services.measurement_audit import audit_recommendations


@pytest.fixture
def session_case():
    dates = ["2026-01-02", "2026-01-05", "2026-01-07", "2026-01-08", "2026-01-09"]
    cycle = {
        "id": "coverage",
        "metadata": {
            "original_decision": {
                "ticker": "AAPL",
                "action": "BUY",
                "horizon": "short",
                "decision_at": "2026-01-01",
                "reference_price": 100,
                "target_price": 120,
                "stop_loss": 90,
            }
        },
    }
    frame = pd.DataFrame(
        {"close": [100] * 6, "high": [101] * 6, "low": [99] * 6},
        index=pd.to_datetime(["2025-12-31"] + dates),
    )
    calendar = {
        "AAPL": {
            "source": "test exchange fixture",
            "coverage_start": "2026-01-01",
            "coverage_end": "2026-01-09",
            "sessions": dates,
        }
    }
    return cycle, frame, calendar


def test_session_audit_accepts_declared_holiday_and_preserves_inputs(session_case):
    cycle, frame, calendar = session_case
    before = deepcopy(calendar)
    result = audit_recommendations(
        [cycle], {"AAPL": frame}, as_of="2026-01-09", session_calendars=calendar
    )
    assert result["observations"][0]["status"] == "expired"
    assert result["observations"][0]["forward_returns_pct"]["5"] == 0
    assert result["measurement_quality"] == "provisional_supplied_session_calendar"
    assert result["promotion_permitted"] is False
    assert calendar == before


@pytest.mark.parametrize("missing", ["2026-01-05", "2026-01-09"])
def test_session_audit_excludes_internal_and_trailing_gaps(session_case, missing):
    cycle, frame, calendar = session_case
    frame = frame.drop(pd.Timestamp(missing))
    result = audit_recommendations(
        [cycle], {"AAPL": frame}, as_of="2026-01-09", session_calendars=calendar
    )
    row = result["observations"][0]
    assert row["exclusion_reason"] == "missing_expected_sessions"
    assert row["missing_sessions"] == [missing]
    assert "forward_returns_pct" not in row


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"coverage_start": "2026-01-02"}, "insufficient_calendar_coverage"),
        ({"coverage_end": "2026-01-08"}, "invalid_session_calendar"),
        ({"sessions": ["2026-01-02", "2026-01-02"]}, "invalid_session_calendar"),
        ({"sessions": ["not-a-date"]}, "invalid_session_calendar"),
        ({"source": ""}, "invalid_session_calendar"),
        ({"sessions": []}, "unexpected_price_sessions"),
    ],
)
def test_session_audit_fails_closed_on_bad_calendar(session_case, change, reason):
    cycle, frame, calendar = session_case
    calendar["AAPL"].update(change)
    result = audit_recommendations(
        [cycle], {"AAPL": frame}, as_of="2026-01-09", session_calendars=calendar
    )
    assert result["excluded_reasons"] == {reason: 1}


def test_session_audit_missing_ticker_does_not_fall_back(session_case):
    cycle, frame, _ = session_case
    result = audit_recommendations(
        [cycle], {"AAPL": frame}, as_of="2026-01-09", session_calendars={}
    )
    assert result["excluded_reasons"] == {"missing_session_calendar": 1}


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
