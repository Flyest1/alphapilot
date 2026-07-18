from datetime import datetime, timezone

import pandas as pd

from app.services.advisory.features.ai_beneficiaries import AIBeneficiariesAnalyzer
from app.services.advisory.features.post_earnings_opportunities import (
    PostEarningsOpportunitiesAnalyzer,
)
from app.services.advisory.features.undervalued_us_stocks import UndervaluedUSStocksAnalyzer
from app.services.market_data_service import MarketDataResult


def statement(rows):
    return pd.DataFrame(
        rows,
        columns=[pd.Timestamp("2026-06-30"), pd.Timestamp("2026-03-31")],
    )


def market_result(start=120.0, end=100.0):
    index = pd.date_range("2022-01-03", periods=1200, freq="B")
    values = pd.Series([start + (end - start) * value / 1199 for value in range(1200)])
    frame = pd.DataFrame(
        {
            "open": values.values,
            "high": values.values,
            "low": values.values,
            "close": values.values,
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
        current_price=end,
    )


class FakeMarketData:
    def fetch_price_history(self, _market, _ticker, _lookback):
        return market_result()


class FakeTicker:
    info = {
        "longName": "Example Corp",
        "trailingPE": 15,
        "forwardPE": 14,
        "priceToBook": 2,
        "enterpriseToEbitda": 9,
    }
    quarterly_financials = statement(
        {
            pd.Timestamp("2026-06-30"): {
                "Total Revenue": 120,
                "Operating Income": 24,
                "Diluted EPS": 2.0,
            },
            pd.Timestamp("2026-03-31"): {
                "Total Revenue": 100,
                "Operating Income": 15,
                "Diluted EPS": 1.0,
            },
        }
    )
    financials = pd.DataFrame(
        {
            pd.Timestamp("2025-12-31"): {"Diluted EPS": 4.0},
            pd.Timestamp("2024-12-31"): {"Diluted EPS": 4.0},
            pd.Timestamp("2023-12-31"): {"Diluted EPS": 4.0},
        }
    )
    quarterly_cashflow = statement(
        {
            pd.Timestamp("2026-06-30"): {"Free Cash Flow": 30},
            pd.Timestamp("2026-03-31"): {"Free Cash Flow": 20},
        }
    )
    quarterly_balance_sheet = statement(
        {
            pd.Timestamp("2026-06-30"): {
                "Cash And Cash Equivalents": 50,
                "Total Debt": 30,
                "Stockholders Equity": 100,
            },
            pd.Timestamp("2026-03-31"): {
                "Cash And Cash Equivalents": 45,
                "Total Debt": 35,
                "Stockholders Equity": 95,
            },
        }
    )


class FakeYFinance:
    def Ticker(self, _ticker):
        return FakeTicker()


class EarningsTicker(FakeTicker):
    def get_earnings_dates(self, limit):
        assert limit == 8
        return pd.DataFrame(
            {
                "EPS Estimate": [2.1],
                "Reported EPS": [2.0],
                "Surprise(%)": [-4.76],
            },
            index=[pd.Timestamp("2026-07-10", tz="UTC")],
        )


class EarningsYFinance:
    def Ticker(self, _ticker):
        return EarningsTicker()


class EmptyTicker:
    info = {}
    quarterly_financials = pd.DataFrame()
    quarterly_cashflow = pd.DataFrame()
    quarterly_balance_sheet = pd.DataFrame()


class EmptyYFinance:
    def Ticker(self, _ticker):
        return EmptyTicker()


class FakeFilingProvider:
    def get_latest_earnings_release(self, _ticker):
        return {
            "filed_at": "2026-05-01",
            "provider": "sec_edgar",
            "url": "https://example.test/filing",
            "decline_reason": "단기 비용 증가",
            "market_disappointment": "다음 분기 비용 전망",
            "guidance": "연간 매출 성장 전망 유지",
            "management_highlights": ["장기 계약 증가"],
            "overreaction_case": "매출과 마진은 개선",
            "long_term_rerating_case": "현금흐름 개선",
            "key_risks": ["비용 통제"],
        }

    def get_ai_disclosures(self, _ticker):
        return [
            {
                "text": (
                    "AI revenue increased as our generative AI platform added new customer "
                    "contract growth and automation cost reduction using a proprietary model."
                ),
                "as_of": "2026-06-30",
                "url": "https://example.test/ai",
                "metrics": {"ai_revenue_growth_pct": 25},
            }
        ]


def test_undervalued_analysis_scores_improving_fundamentals_without_fabricating_guidance():
    result = UndervaluedUSStocksAnalyzer(
        FakeMarketData(),
        FakeYFinance(),
        now_provider=lambda: datetime(2026, 7, 17, tzinfo=timezone.utc),
    ).analyze(["EXM"])

    row = result["rows"][0]
    assert row["three_month_return_pct"] < 0
    assert row["quarterly_revenue_growth_pct"] == 20.0
    assert row["operating_margin_change_pct_points"] == 5.0
    assert row["free_cash_flow_change_pct"] == 50.0
    assert row["historical_valuation_status"] == "available_with_limitations"
    assert row["historical_valuation_comparison"]["sample_size"] == 3
    assert (
        row["historical_valuation_comparison"]["current_trailing_pe_vs_historical_median_pct"]
        is not None
    )
    assert "look-ahead bias" in row["historical_valuation_comparison"]["limitations"][0]
    assert row["guidance"] == "회사 공식 가이던스 데이터 없음"
    assert result["top_candidates"][0]["ticker"] == "EXM"
    assert result["data_quality"]["status"] == "fresh"


def test_undervalued_analysis_does_not_score_or_rank_without_required_evidence():
    result = UndervaluedUSStocksAnalyzer(FakeMarketData(), EmptyYFinance()).analyze(["EXM"])

    row = result["rows"][0]
    assert row["analysis_status"] == "data-limited"
    assert row["action"] == "WATCH"
    assert row["investment_score"] is None
    assert result["top_candidates"] == []


class NoHistoricalValuationMarketData:
    def fetch_price_history(self, _market, _ticker, lookback):
        assert lookback in {120, 1260}
        result = market_result()
        if lookback == 1260:
            result.dataframe = result.dataframe.loc["2026-01-01":]
        return result


def test_undervalued_analysis_fails_closed_without_historical_valuation_samples():
    result = UndervaluedUSStocksAnalyzer(NoHistoricalValuationMarketData(), FakeYFinance()).analyze(
        ["EXM"]
    )

    row = result["rows"][0]
    assert row["historical_valuation_comparison"] is None
    assert row["historical_valuation_status"] == "data-limited"
    assert row["analysis_status"] == "data-limited"
    assert row["investment_score"] is None
    assert result["top_candidates"] == []


def test_post_earnings_analysis_uses_official_release_and_financials():
    result = PostEarningsOpportunitiesAnalyzer(
        FakeMarketData(),
        FakeYFinance(),
        filing_provider=FakeFilingProvider(),
    ).analyze(["EXM"])

    row = result["rows"][0]
    assert row["guidance"] == "연간 매출 성장 전망 유지"
    assert row["quarterly_revenue_growth_pct"] == 20.0
    assert row["eps_change_pct"] == 100.0
    assert row["interest_price_range"] is not None
    assert row["provider"] == "sec_edgar"


def test_post_earnings_analysis_does_not_score_or_rank_without_release():
    result = PostEarningsOpportunitiesAnalyzer(FakeMarketData(), FakeYFinance()).analyze(["EXM"])

    row = result["rows"][0]
    assert row["analysis_status"] == "data-limited"
    assert row["action"] == "WATCH"
    assert row["opportunity_score"] is None
    assert result["rankings"] == []


def test_post_earnings_analysis_uses_yfinance_event_when_official_release_is_missing():
    result = PostEarningsOpportunitiesAnalyzer(
        FakeMarketData(),
        EarningsYFinance(),
        now_provider=lambda: datetime(2026, 7, 17, tzinfo=timezone.utc),
    ).analyze(["EXM"], lookback_days=14)

    row = result["rows"][0]
    assert row["earnings_release_date"] == "2026-07-10"
    assert row["provider"] == "yfinance_earnings_calendar"
    assert row["market_disappointment"] == "yfinance 집계 EPS가 시장 예상치를 하회했습니다."
    assert row["analysis_status"] == "data-limited"
    assert row["action"] == "WATCH"
    assert result["rankings"] == []


def test_ai_beneficiary_requires_quantitative_disclosure_for_verified_classification():
    result = AIBeneficiariesAnalyzer(
        FakeMarketData(),
        FakeYFinance(),
        disclosure_provider=FakeFilingProvider(),
    ).analyze(["EXM"])

    row = result["rows"][0]
    assert row["classification"] == "verified_ai_beneficiary"
    assert row["quantitative_evidence_count"] == 1
    assert row["disclosure_evidence"][0]["metrics"] == {"ai_revenue_growth_pct": 25}
    assert "revenue_contribution" in row["disclosure_evidence"][0]["matched_criteria"]
    assert row["disclosure_evidence"][0]["supporting_sentences"]
    assert result["evidence"][0]["provider"] == "official_disclosure"
    assert result["verified_ai_beneficiaries"][0]["ticker"] == "EXM"


def test_ai_beneficiary_requested_theme_filters_verified_classification():
    analyzer = AIBeneficiariesAnalyzer(
        FakeMarketData(),
        FakeYFinance(),
        disclosure_provider=FakeFilingProvider(),
    )

    matching = analyzer.analyze(["EXM"], themes=["generative ai"])
    non_matching = analyzer.analyze(["EXM"], themes=["inference"])

    assert matching["rows"][0]["matched_themes"] == ["generative ai"]
    assert matching["rows"][0]["classification"] == "verified_ai_beneficiary"
    assert non_matching["rows"][0]["matched_themes"] == []
    assert non_matching["rows"][0]["classification"] == "ai_theme_caution"


def test_ai_beneficiary_without_disclosures_is_caution_not_fabricated():
    result = AIBeneficiariesAnalyzer(FakeMarketData(), FakeYFinance()).analyze(["EXM"])

    assert result["rows"][0]["classification"] == "ai_theme_caution"
    assert result["rows"][0]["disclosure_count"] == 0
    assert result["rows"][0]["analysis_status"] == "data-limited"
    assert result["rows"][0]["action"] == "WATCH"
    assert result["rows"][0]["investment_appeal_10"] is None
    assert [row["ticker"] for row in result["ai_theme_caution"]] == ["EXM"]
    assert result["data_quality"]["status"] == "data-limited"


def test_ai_beneficiary_caution_prioritizes_available_scores_without_dropping_data_limited():
    analyzer = AIBeneficiariesAnalyzer(FakeMarketData(), FakeYFinance())
    analyzer._analyze_ticker = lambda ticker, _generated_at: {
        "ticker": ticker,
        "classification": "ai_theme_caution",
        "analysis_status": "available" if ticker == "AMD" else "data-limited",
        "overheating_risk_10": 7.5 if ticker == "AMD" else None,
        "disclosure_evidence": [],
        "as_of": None,
    }

    result = analyzer.analyze(["NVDA", "AMD", "MSFT"])

    assert [row["ticker"] for row in result["ai_theme_caution"]] == ["AMD", "MSFT", "NVDA"]
    assert all(
        row["overheating_risk_10"] is None
        for row in result["ai_theme_caution"]
        if row["analysis_status"] == "data-limited"
    )
