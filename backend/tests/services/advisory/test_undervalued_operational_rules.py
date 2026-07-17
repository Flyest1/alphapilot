from __future__ import annotations

import pandas as pd

from app.services.advisory.features.undervalued_us_stocks import UndervaluedUSStocksAnalyzer
from app.services.market_data_service import MarketDataResult


def _market_result(three_month_return_pct: float) -> MarketDataResult:
    index = pd.date_range("2022-01-03", periods=1200, freq="B")
    start_price = 100.0
    trailing_prices = [
        start_price * (1 + three_month_return_pct / 100 * day / 65) for day in range(66)
    ]
    prices = [start_price] * (len(index) - len(trailing_prices)) + trailing_prices
    frame = pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": 1000,
        },
        index=index,
    )
    return MarketDataResult(
        dataframe=frame,
        last_trading_date=index[-1].to_pydatetime(),
        is_stale=False,
        provider="yfinance",
        data_quality_note="ok",
        current_price=prices[-1],
    )


def _quarterly_statement(current: dict[str, float], previous: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            pd.Timestamp("2026-06-30"): current,
            pd.Timestamp("2026-03-31"): previous,
        }
    )


class _Ticker:
    info = {
        "longName": "Example Corp",
        "trailingPE": 15,
        "forwardPE": 14,
        "priceToBook": 2,
        "enterpriseToEbitda": 9,
    }
    financials = pd.DataFrame(
        {
            pd.Timestamp("2025-12-31"): {"Diluted EPS": 4.0},
            pd.Timestamp("2024-12-31"): {"Diluted EPS": 4.0},
            pd.Timestamp("2023-12-31"): {"Diluted EPS": 4.0},
        }
    )
    quarterly_balance_sheet = _quarterly_statement(
        {
            "Cash And Cash Equivalents": 50,
            "Total Debt": 30,
            "Stockholders Equity": 100,
        },
        {
            "Cash And Cash Equivalents": 45,
            "Total Debt": 35,
            "Stockholders Equity": 95,
        },
    )

    def __init__(self, improving: bool) -> None:
        if improving:
            self.quarterly_financials = _quarterly_statement(
                {"Total Revenue": 120, "Operating Income": 24},
                {"Total Revenue": 100, "Operating Income": 15},
            )
            self.quarterly_cashflow = _quarterly_statement(
                {"Free Cash Flow": 30}, {"Free Cash Flow": 20}
            )
        else:
            self.quarterly_financials = _quarterly_statement(
                {"Total Revenue": 80, "Operating Income": 10},
                {"Total Revenue": 100, "Operating Income": 20},
            )
            self.quarterly_cashflow = _quarterly_statement(
                {"Free Cash Flow": 10}, {"Free Cash Flow": 20}
            )


class _MarketDataService:
    def __init__(self) -> None:
        self._returns = {"PYPL": 19.41, "GOOD": -15.0}

    def fetch_price_history(self, _market: str, ticker: str, _lookback: int) -> MarketDataResult:
        return _market_result(self._returns[ticker])


class _YFinance:
    def Ticker(self, ticker: str) -> _Ticker:
        return _Ticker(improving=ticker == "GOOD")


class _SecFilingProvider:
    def get_latest_earnings_release(self, _ticker: str) -> dict[str, object]:
        return {
            "provider": "sec_edgar",
            "key_risks": [
                "Consumer spending may remain volatile. This second sentence must not be used.",
                "A later risk must not be used.",
            ],
        }


def _analyzer() -> UndervaluedUSStocksAnalyzer:
    return UndervaluedUSStocksAnalyzer(
        _MarketDataService(), _YFinance(), filing_provider=_SecFilingProvider()
    )


def test_positive_return_and_worsening_fundamentals_are_excluded_from_top_candidates():
    result = _analyzer().analyze(["PYPL"])

    row = result["rows"][0]
    assert row["three_month_return_pct"] == 19.41
    assert row["candidate_eligible"] is False
    assert row["action"] == "WATCH"
    assert "three_month_return_not_negative" in row["eligibility_reasons"]
    assert "no_positive_fundamental_improvement" in row["eligibility_reasons"]
    assert result["top_candidates"] == []


def test_eligible_declining_stock_with_improving_fundamentals_is_a_top_candidate():
    result = _analyzer().analyze(["GOOD"])

    row = result["rows"][0]
    assert row["candidate_eligible"] is True
    assert row["action"] == "BUY"
    assert "three_month_return_negative" in row["eligibility_reasons"]
    assert "revenue_growth_positive" in row["eligibility_reasons"]
    assert [candidate["ticker"] for candidate in result["top_candidates"]] == ["GOOD"]


def test_market_risk_uses_first_safe_sentence_from_official_sec_release():
    result = _analyzer().analyze(["GOOD"])

    assert result["rows"][0]["market_risk"] == "Consumer spending may remain volatile."
