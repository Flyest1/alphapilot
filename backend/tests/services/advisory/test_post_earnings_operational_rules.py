from datetime import datetime, timezone

import pandas as pd

from app.services.advisory.features.post_earnings_opportunities import (
    PostEarningsOpportunitiesAnalyzer,
)
from app.services.market_data_service import MarketDataResult


class MarketDataService:
    def fetch_price_history(self, _market, ticker, _lookback):
        index = pd.bdate_range("2026-06-15", periods=30)
        event_price = 100.0
        current_price = 107.55 if ticker == "ADBE" else 90.0
        closes = [event_price] * (len(index) - 1) + [current_price]
        return MarketDataResult(
            dataframe=pd.DataFrame({"close": closes}, index=index),
            last_trading_date=index[-1].to_pydatetime(),
            is_stale=False,
            provider="yfinance",
            data_quality_note="ok",
            current_price=current_price,
        )


class Ticker:
    info = {"longName": "Example Corp"}
    quarterly_financials = pd.DataFrame(
        {
            pd.Timestamp("2026-06-30"): {
                "Total Revenue": 120.0,
                "Operating Income": 24.0,
                "Diluted EPS": 2.0,
            },
            pd.Timestamp("2026-03-31"): {
                "Total Revenue": 100.0,
                "Operating Income": 15.0,
                "Diluted EPS": 1.0,
            },
        }
    )


class YFinance:
    def Ticker(self, _ticker):
        return Ticker()


class FilingProvider:
    def get_latest_earnings_release(self, ticker):
        return {
            "filed_at": "2026-07-01",
            "provider": "sec_edgar",
            "url": f"https://example.test/{ticker}",
        }


def test_post_earnings_rankings_require_decline_and_financial_improvement():
    result = PostEarningsOpportunitiesAnalyzer(
        MarketDataService(),
        YFinance(),
        filing_provider=FilingProvider(),
        now_provider=lambda: datetime(2026, 7, 17, tzinfo=timezone.utc),
    ).analyze(["ADBE", "CRM"])

    rows = {row["ticker"]: row for row in result["rows"]}
    adobe = rows["ADBE"]
    crm = rows["CRM"]

    assert adobe["post_earnings_return_pct"] == 7.55
    assert adobe["ranking_eligible"] is False
    assert "post_earnings_return_not_negative" in adobe["ranking_eligibility_reasons"]
    assert adobe["action"] == "WATCH"
    assert adobe["decline_reason"] is None
    assert adobe["overreaction_case"] is None

    assert crm["post_earnings_return_pct"] == -10.0
    assert crm["quarterly_revenue_growth_pct"] == 20.0
    assert crm["ranking_eligible"] is True
    assert "post_earnings_return_negative" in crm["ranking_eligibility_reasons"]
    assert "revenue_growth_positive" in crm["ranking_eligibility_reasons"]
    assert [row["ticker"] for row in result["rankings"]] == ["CRM"]
