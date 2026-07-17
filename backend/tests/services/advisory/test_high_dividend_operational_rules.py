import pandas as pd
import pytest

from app.services.advisory.features.high_dividend_etfs import (
    MAX_RETURN_HISTORY_SHORTFALL_DAYS,
    HighDividendEtfService,
)


def test_total_return_uses_exact_ten_year_calendar_boundary():
    close = pd.Series(
        [100.0, 125.0, 200.0],
        index=pd.to_datetime(["2016-07-17", "2016-07-18", "2026-07-17"]),
    )

    assert HighDividendEtfService._total_return(close, 10) == 100.0


def test_total_return_fails_closed_when_history_is_materially_shorter_than_requested():
    requested_start = pd.Timestamp("2016-07-17")
    close = pd.Series(
        [100.0, 200.0],
        index=pd.to_datetime(
            [
                requested_start + pd.Timedelta(days=MAX_RETURN_HISTORY_SHORTFALL_DAYS + 1),
                "2026-07-17",
            ]
        ),
    )

    assert HighDividendEtfService._total_return(close, 10) is None


def test_total_return_uses_first_observation_after_five_year_calendar_boundary():
    close = pd.Series(
        [100.0, 130.0],
        index=pd.to_datetime(["2021-07-19", "2026-07-17"]),
    )

    assert HighDividendEtfService._total_return(close, 5) == pytest.approx(30.0)
