from datetime import datetime, timezone

import pandas as pd
from app.services.advisory.features import top_holdings_from_funds_data
from app.services.advisory.features.etf_overlap import EtfOverlapService
from app.services.advisory.features.etf_rebalancing import EtfRebalancingService
from app.services.advisory.features.high_dividend_etfs import HighDividendEtfService
from app.services.advisory.features.sector_outlook import SectorOutlookService
from app.services.market_data_service import MarketDataResult


def _history(periods: int = 2_700, start: float = 100.0) -> pd.DataFrame:
    index = pd.bdate_range("2015-01-01", periods=periods)
    close = [start * (1.00025**day) for day in range(periods)]
    volume = [1_000_000 + day * 100 for day in range(periods)]
    return pd.DataFrame({"close": close, "volume": volume}, index=index)


class FakeMarketDataService:
    def __init__(self, stale_tickers=None):
        self.stale_tickers = set(stale_tickers or [])

    def fetch_price_history(self, market, ticker, lookback_days, stale_data_business_days):
        frame = _history(start=100 + len(ticker))
        return MarketDataResult(
            dataframe=frame,
            last_trading_date=datetime(2026, 7, 17, tzinfo=timezone.utc),
            is_stale=ticker in self.stale_tickers,
            provider="yfinance",
            data_quality_note=(
                "stale market data; data-limited" if ticker in self.stale_tickers else "ok"
            ),
            current_price=float(frame.iloc[-1]["close"]),
        )


class FakeFundsData:
    top_holdings = pd.DataFrame(
        {"Holding Percent": [0.1, 0.08, 0.06]}, index=["AAPL", "MSFT", "NVDA"]
    )
    sector_weightings = {"technology": 0.35, "financial_services": 0.2}


class FakeTicker:
    funds_data = FakeFundsData()
    dividends = pd.Series(
        [0.5] * 24,
        index=pd.date_range("2020-01-31", periods=24, freq="QE"),
        dtype=float,
    )

    def __init__(self, ticker):
        self.ticker = ticker
        self.info = {
            "earningsGrowth": 0.12,
            "revenueGrowth": 0.08,
            "trailingPE": 24.0,
            "forwardPE": 21.0,
            "priceToBook": 4.0,
        }

    def history(self, period, auto_adjust):
        return _history().rename(columns={"close": "Close"})


class FakeYfinance:
    def Ticker(self, ticker):
        return FakeTicker(ticker)


class MissingHoldingsFundsData:
    top_holdings = pd.DataFrame({"unsupported": [0.1]}, index=["AAPL"])
    sector_weightings = {"technology": 0.35}


class MissingHoldingsTicker(FakeTicker):
    funds_data = MissingHoldingsFundsData()


class MissingHoldingsYfinance:
    def Ticker(self, ticker):
        return MissingHoldingsTicker(ticker)


class HistoryTrackingTicker(FakeTicker):
    def __init__(self, ticker):
        super().__init__(ticker)
        self.history_periods = []

    def history(self, period, auto_adjust):
        self.history_periods.append(period)
        return super().history(period, auto_adjust)


class HistoryTrackingYfinance:
    def __init__(self):
        self.ticker = HistoryTrackingTicker("SCHD")

    def Ticker(self, ticker):
        return self.ticker


class FakeMacroProvider:
    def fetch_context(self, series_ids, observation_start, observation_end):
        return {
            "provider": "fred",
            "status": "ok",
            "retrieved_at": "2026-07-17T00:00:00+00:00",
            "limitations": [],
            "series": [
                {
                    "series_id": "FEDFUNDS",
                    "label": "Federal Funds Rate",
                    "category": "policy_rate",
                    "units": "Percent",
                    "frequency": "Monthly",
                    "observations": [
                        {"observation_date": "2026-06-01", "value": 4.25},
                        {"observation_date": "2026-07-01", "value": 4.0},
                    ],
                    "realtime_vintage": {"realtime_start": "2026-07-17"},
                }
            ],
        }


class FakeNportProvider:
    def get_nport_delayed_data(self, ticker):
        return {
            "status": "available",
            "series_id": f"S-{ticker}",
            "public_data_delay_days": 60,
            "flow_fields": {"sales": 10.0, "redemption": 8.0},
            "filings": [{"report_date": "2026-04-30"}],
        }


def test_etf_rebalancing_calculates_metrics_scenarios_and_marks_stale_data():
    service = EtfRebalancingService(FakeMarketDataService(stale_tickers={"TLT"}), FakeYfinance())

    result = service.analyze(
        [{"ticker": "SCHD", "weight_pct": 60}, {"ticker": "TLT", "weight_pct": 40}]
    )

    schd = result["etfs"][0]
    assert schd["metrics"]["return_1y_pct"] is not None
    assert schd["metrics"]["return_3y_pct"] is not None
    assert schd["metrics"]["return_basis"] == "distribution-adjusted total return"
    assert schd["metrics"]["annualized_volatility_pct"] is not None
    assert schd["metrics"]["trailing_distribution_yield_pct"] is not None
    assert schd["top_holdings"][0]["ticker"] == "AAPL"
    assert schd["current_weight_pct"] == 60
    assert result["etfs"][1]["data_quality"] == "data-limited"
    assert result["current_weight_metadata"]["status"] == "available"
    assert result["top10_overlap"][0]["minimum_confirmed_top10_overlap_pct"] == 24
    assert all(plan["excluded_tickers"] == ["TLT"] for plan in result["scenarios"])
    assert all(plan["weight_changes_vs_current_pct"] is not None for plan in result["scenarios"])
    assert all(plan["expected_return_direction"] for plan in result["scenarios"])
    assert all(plan["primary_risk"] for plan in result["scenarios"])
    assert all(plan["suitable_investor"] for plan in result["scenarios"])
    assert all(
        sum(row["target_weight_pct"] for row in plan["target_weights"]) == 100
        for plan in result["scenarios"]
    )


def test_top_holdings_accepts_yfinance_holding_percent_column():
    holdings, status = top_holdings_from_funds_data(FakeFundsData())

    assert status == "available"
    assert holdings == [
        {"ticker": "AAPL", "weight_pct": 10},
        {"ticker": "MSFT", "weight_pct": 8},
        {"ticker": "NVDA", "weight_pct": 6},
    ]


def test_etf_rebalancing_requests_history_beyond_three_year_return_boundary():
    yfinance = HistoryTrackingYfinance()
    result = EtfRebalancingService(FakeMarketDataService(), yfinance).analyze(["SCHD"])

    assert yfinance.ticker.history_periods == ["5y"]
    assert result["etfs"][0]["metrics"]["return_3y_pct"] is not None


def test_etf_rebalancing_marks_missing_required_fund_data_partial():
    result = EtfRebalancingService(FakeMarketDataService(), MissingHoldingsYfinance()).analyze(
        ["SCHD"]
    )

    assert result["etfs"][0]["data_quality"] == "partial"
    assert result["data_quality"]["status"] == "partial"
    assert result["data_quality"]["partial_sources"] == 1


def test_high_dividend_etfs_returns_ranked_five_and_five_without_network_calls():
    tickers = [f"DIV{index}" for index in range(10)]
    service = HighDividendEtfService(FakeMarketDataService(), FakeYfinance())

    result = service.analyze(tickers)

    assert len(result["caution_etfs"]) == 5
    assert len(result["relatively_stable_etfs"]) == 5
    assert result["etfs"][0]["total_return_5y_pct"] is not None
    assert result["etfs"][0]["total_return_10y_pct"] is not None
    assert result["etfs"][0]["distribution"]["stability"] == "stable"
    assert result["etfs"][0]["distribution"]["trailing_12m_distribution_yield_pct"] is not None
    assert result["etfs"][0]["distribution"]["distribution_cut_risk"]["status"] == "available"
    assert result["etfs"][0]["holdings_quality"]["status"] == "data-limited"
    assert result["etfs"][0]["sector_concentration"]["dominant_sector"] == "technology"
    assert "분배금 수익률" in result["beginner_explanation"]


def test_etf_overlap_uses_top_holdings_for_overlap_and_actual_company_exposure():
    service = EtfOverlapService(FakeYfinance())

    result = service.analyze(
        [{"ticker": "QQQ", "weight_pct": 60}, {"ticker": "SCHD", "weight_pct": 40}]
    )

    assert result["pairwise_overlap"][0]["common_holdings"] == ["AAPL", "MSFT", "NVDA"]
    assert result["pairwise_overlap"][0]["top10_overlap_pct"] == 24
    assert result["actual_company_exposure"][0] == {"ticker": "AAPL", "portfolio_exposure_pct": 10}
    assert result["style_exposure_approximation"]["technology"] == 60
    assert result["requested_exposure_summary"]["technology_pct"] == 35
    assert result["requested_exposure_summary"]["financial_pct"] == 20
    assert result["requested_exposure_summary"]["semiconductor_minimum_confirmed_pct"] == 6
    assert result["diversification_assessment"]["level"] == "moderate"
    assert len(result["rebalancing_plans"]) == 3
    assert result["pairwise_overlap"][0]["coverage_status"] == "available"
    assert result["pairwise_overlap"][0]["left_top10_coverage_pct"] == 24
    assert len(result["target_weight_scenarios"]) == 3
    assert all(item["provider"] == "yfinance" for item in result["evidence"])


def test_etf_overlap_fails_closed_when_holdings_coverage_is_unavailable():
    result = EtfOverlapService(MissingHoldingsYfinance()).analyze(
        [{"ticker": "QQQ", "weight_pct": 60}, {"ticker": "SCHD", "weight_pct": 40}]
    )

    assessment = result["diversification_assessment"]
    assert assessment["status"] == "data-limited"
    assert assessment["level"] is None
    assert assessment["largest_company_exposure_pct"] is None
    assert assessment["maximum_pairwise_top10_overlap_pct"] is None
    assert result["pairwise_overlap"][0]["top10_overlap_pct"] is None
    assert all(plan["status"] == "data-limited" for plan in result["rebalancing_plans"])
    assert all(plan["condition"] is None for plan in result["rebalancing_plans"])


def test_sector_outlook_covers_fixed_proxy_universe_and_three_portfolios():
    service = SectorOutlookService(FakeMarketDataService(), FakeYfinance())

    result = service.analyze()

    assert len(result["sectors"]) == 10
    assert result["proxy_universe"] == {
        "technology": "XLK",
        "semiconductors": "SMH",
        "healthcare": "XLV",
        "financials": "XLF",
        "energy": "XLE",
        "consumer_discretionary": "XLY",
        "industrials": "XLI",
        "utilities": "XLU",
        "real_estate": "XLRE",
        "long_treasury_bonds": "TLT",
    }
    assert all(row["attractiveness_score"] is not None for row in result["sectors"])
    assert all(row["favorable_factors"] is not None for row in result["sectors"])
    assert all(row["representative_holdings"] for row in result["sectors"])
    assert all(row["fundamentals"]["earnings_growth_pct"] == 12 for row in result["sectors"])
    assert all(row["fundamentals"]["forward_pe"] == 21 for row in result["sectors"])
    assert all(
        row["etf_flow_context"]["provider"] == "yfinance_price_volume_proxy"
        and row["etf_flow_context"]["status"] == "proxy"
        for row in result["sectors"]
    )
    assert [row["investor_profile"] for row in result["investor_portfolios"]] == [
        "aggressive",
        "balanced",
        "conservative",
    ]
    assert all(
        sum(item["target_weight_pct"] for item in row["target_weights"]) == 100
        for row in result["investor_portfolios"]
    )
    assert result["data_quality"]["status"] == "partial"


def test_sector_outlook_attaches_fred_context_and_delayed_nport_without_changing_score():
    baseline = SectorOutlookService(FakeMarketDataService(), FakeYfinance()).analyze(
        {"technology": "XLK"}
    )
    result = SectorOutlookService(
        FakeMarketDataService(),
        FakeYfinance(),
        macro_provider=FakeMacroProvider(),
        fund_flow_provider=FakeNportProvider(),
    ).analyze({"technology": "XLK"})

    assert (
        result["sectors"][0]["attractiveness_score"]
        == baseline["sectors"][0]["attractiveness_score"]
    )
    assert result["macro_context"]["series"][0]["series_id"] == "FEDFUNDS"
    assert result["fred_notice"].startswith("This product uses the FRED")
    assert result["evidence"][-1]["evidence_id"].startswith("fred:FEDFUNDS:")
    assert result["evidence"][-1]["status"] == "available"
    assert result["data_quality"]["status"] == "available"
    flow = result["sectors"][0]["etf_flow_context"]
    assert flow["provider"] == "sec_edgar_nport"
    assert "delayed" in flow["limitations"][0]


def test_sector_outlook_marks_missing_fred_context_partial_even_with_nport():
    result = SectorOutlookService(
        FakeMarketDataService(),
        FakeYfinance(),
        fund_flow_provider=FakeNportProvider(),
    ).analyze({"technology": "XLK"})

    assert result["sectors"][0]["data_quality"] == "fresh"
    assert result["evidence"][-1]["evidence_id"] == "fred:unavailable"
    assert result["data_quality"]["status"] == "partial"


def test_missing_market_data_is_not_replaced_with_fabricated_metrics():
    service = SectorOutlookService(FakeMarketDataService(stale_tickers={"XLK"}))

    result = service.analyze({"technology": "XLK"})

    row = result["sectors"][0]
    assert row["attractiveness_score"] is None
    assert row["attractiveness_label"] == "data-limited"
    assert result["investor_portfolios"][0]["target_weights"] == []
