from app.services.advisory.features.common import percent_change


def test_percent_change_keeps_direction_for_negative_bases():
    assert percent_change(110, 100) == 10.0
    assert percent_change(-200, -100) == -100.0  # cash burn doubled: deterioration
    assert percent_change(-50, -100) == 50.0  # burn halved: improvement
    assert percent_change(10, 0) is None
    assert percent_change(None, 10) is None


def test_dividend_metrics_ignore_partial_year_and_stale_distributions():
    from datetime import datetime

    import pandas as pd

    from app.services.advisory.features.high_dividend_etfs import HighDividendEtfService

    quarterly = pd.Series(
        [1.0] * 19,
        index=pd.date_range("2021-03-31", periods=19, freq="QE"),
    )  # 2021Q1 .. 2025Q3: 2025 holds only three payments so far
    metrics = HighDividendEtfService._distribution_metrics(
        quarterly, 100.0, as_of=datetime(2025, 10, 15)
    )
    assert metrics["stability"] == "stable"
    assert metrics["growth_3y_pct"] == 0.0

    stopped = pd.Series([1.0] * 8, index=pd.date_range("2020-03-31", periods=8, freq="QE"))
    stale = HighDividendEtfService._distribution_metrics(
        stopped, 100.0, as_of=datetime(2024, 6, 30)
    )
    assert stale["trailing_12m_distribution_yield_pct"] is None
    assert stale["stability"] == "data-limited"


def test_year_ago_observation_uses_dates_not_row_counts():
    from app.services.advisory.features.sector_outlook import SectorOutlookService

    daily = [
        {"observation_date": f"2026-06-{day:02d}", "value": float(day)} for day in range(1, 29)
    ]
    assert SectorOutlookService._year_ago_observation(daily) is None
    monthly = [
        {"observation_date": f"{2025 + (month // 12)}-{month % 12 + 1:02d}-01", "value": month}
        for month in range(0, 14)
    ]  # 2025-01 .. 2026-02
    assert SectorOutlookService._year_ago_observation(monthly)["observation_date"] == "2025-02-01"


def test_ai_terms_match_whole_words_only():
    from app.services.advisory.providers.sec_edgar import SecEdgarProvider, _AI_TERM_PATTERN

    text = (
        "Our aircraft fleet expanded in Shanghai and Dubai. We aim to aid growth. "
        "We deploy AI models across products. Machine learning improves pricing."
    )
    sentences = SecEdgarProvider._sentences(text, _AI_TERM_PATTERN, 12)
    assert sentences == [
        "We deploy AI models across products.",
        "Machine learning improves pricing.",
    ]


def test_negative_equity_does_not_earn_low_leverage_points():
    from app.services.advisory.features.undervalued_us_stocks import UndervaluedUSStocksAnalyzer

    def score(debt_to_equity):
        return UndervaluedUSStocksAnalyzer._score(None, None, None, None, debt_to_equity, None, 0)

    assert score(50.0) == 5
    assert score(-250.0) == 0
