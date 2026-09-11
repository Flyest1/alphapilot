from copy import deepcopy

import pytest

from app.services.price_revision_audit import compare_price_evidence


def bar(day, price, **extra):
    return {"date": day, "open": price, "high": price, "low": price, "close": price, **extra}


def test_revisions_are_diagnostics_and_do_not_rewrite_inputs():
    old = [bar("2026-06-01", 100), bar("2026-06-02", 102)]
    new = [bar("2026-06-01", 50), bar("2026-06-02", 51, split=2, dividend=1)]
    before = deepcopy(old)
    result = compare_price_evidence(old, new, start="2026-06-01", end="2026-06-02")
    assert result["matched_session_count"] == 2
    assert result["revised_close_count"] == 2
    assert result["revisions"][0]["close_change_pct"] == -50
    assert result["corporate_actions"] == [{"date": "2026-06-02", "split": 2, "dividend": 1}]
    assert result["price_basis_verified"] is False
    assert old == before


def test_missing_dates_and_roundoff_are_distinguished():
    result = compare_price_evidence(
        [bar("2026-06-01", 100), bar("2026-06-02", 100)],
        [bar("2026-06-01", 100.000001), bar("2026-06-03", 100)],
        start="2026-06-01",
        end="2026-06-03",
    )
    assert result["revised_close_count"] == 0
    assert result["missing_in_refreshed"] == ["2026-06-02"]
    assert result["missing_in_archived"] == ["2026-06-03"]


@pytest.mark.parametrize("invalid", [float("nan"), -1, True, None])
def test_invalid_prices_cannot_be_counted_as_matches(invalid):
    result = compare_price_evidence(
        [bar("2026-06-01", invalid)],
        [bar("2026-06-01", 100)],
        start="2026-06-01",
        end="2026-06-01",
    )
    assert result["status"] == "invalid_input"
    assert "matched_session_count" not in result


def test_duplicate_dates_are_rejected_instead_of_silently_overwritten():
    result = compare_price_evidence(
        [bar("2026-06-01", 100), bar("2026-06-01", 200)],
        [],
        start="2026-06-01",
        end="2026-06-02",
    )
    assert result["status"] == "invalid_input"


def test_future_rows_are_not_evidence_for_the_requested_window():
    result = compare_price_evidence(
        [bar("2026-06-01", 100)],
        [bar("2026-06-01", 100), bar("2026-06-02", 50, split=2)],
        start="2026-06-01",
        end="2026-06-01",
    )
    assert result["revised_close_count"] == 0
    assert result["corporate_actions"] == []


def test_high_low_revisions_are_visible_even_when_close_is_unchanged():
    result = compare_price_evidence(
        [bar("2026-06-01", 100)],
        [bar("2026-06-01", 100, high=110)],
        start="2026-06-01",
        end="2026-06-01",
    )
    assert result["revised_close_count"] == 0
    assert result["revisions"][0]["changed_fields"] == ["high"]
