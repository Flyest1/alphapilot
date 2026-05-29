from datetime import datetime, timezone

import pandas as pd

from app.db.supabase_client import InMemoryRepository
from app.models.report import ReportContent
from app.services.market_data_service import MarketDataResult
from app.services.report_service import DISCLAIMER, ReportService
from app.services.technical_analysis_service import TechnicalAnalysisResult


def market_frame():
    index = pd.date_range("2026-01-01", periods=130, freq="B")
    return pd.DataFrame(
        {
            "open": range(1, 131),
            "high": range(2, 132),
            "low": range(0, 130),
            "close": range(50, 180),
            "volume": range(1000, 1130),
        },
        index=index,
    )


class FakeMarketData:
    def __init__(self):
        self.frame = market_frame()

    def fetch_price_history(self, *_args, **_kwargs):
        return MarketDataResult(
            dataframe=self.frame,
            last_trading_date=datetime(2026, 6, 30, tzinfo=timezone.utc),
            is_stale=False,
            provider="mock",
            data_quality_note="ok",
            current_price=179,
        )

    def fetch_major_indices(self, report_type, **_kwargs):
        return {"KOSPI" if report_type == "domestic" else "S&P 500": self.fetch_price_history()}


class FakeMarketDataWithFx(FakeMarketData):
    def fetch_usd_krw_rate(self, fallback):
        return 1450


class FakeTechnical:
    def analyze(self, ticker, _dataframe):
        return TechnicalAnalysisResult(
            ticker=ticker,
            current_price=179,
            indicators={"rsi_14": 60},
            technical_score=85,
            score_breakdown={
                "trend": 30,
                "momentum": 25,
                "volume": 15,
                "volatility": 15,
                "price_position": 0,
            },
            trend_label="strong bullish setup",
            data_quality_note="ok",
        )


class FailingAI:
    def generate_report(self, _prompt, _context):
        raise RuntimeError("LLM unavailable")


class RetryAI:
    def __init__(self):
        self.calls = 0
        self.contexts = []

    def generate_report(self, _prompt, context):
        self.calls += 1
        self.contexts.append(context)
        if self.calls == 1:
            return {"report_type": "domestic"}
        return {
            "report_type": "domestic",
            "generated_at": "2026-05-21T08:30:00+09:00",
            "market_summary": {
                "summary": "validated report",
                "key_indices": [],
                "macro_factors": [],
            },
            "portfolio_summary": {
                "total_market_value": 179,
                "total_return_rate": 79,
                "risk_level": "medium",
                "allocation_comment": "balanced",
            },
            "key_risks": [],
            "opportunities": [],
            "asset_strategies": [],
            "disclaimer": DISCLAIMER,
        }


class FakeNews:
    def __init__(self):
        self.calls = []

    def fetch_report_context(self, report_type, assets):
        self.calls.append((report_type, assets))
        return {
            "provider": "gdelt_doc_2_0",
            "status": "ok",
            "articles": [
                {
                    "query": "mock",
                    "title": "Semiconductor demand improves",
                    "domain": "example.com",
                    "url": "https://example.com/news",
                }
            ],
            "queries": ["mock"],
        }


def seeded_repo():
    repo = InMemoryRepository()
    repo.create_asset(
        {
            "market": "KR",
            "ticker": "005930",
            "name": "Samsung",
            "quantity": 1,
            "avg_price": 100,
            "currency": "KRW",
        }
    )
    return repo


def test_openai_failure_generates_technical_only_report_with_capped_confidence():
    repo = seeded_repo()
    service = ReportService(
        repo,
        market_data_service=FakeMarketData(),
        technical_analysis_service=FakeTechnical(),
        ai_provider=FailingAI(),
        news_service=FakeNews(),
    )

    report = service.generate_report("domestic")
    content = ReportContent.model_validate(report["content"])

    assert "AI reasoning unavailable for this report" in content.key_risks
    assert content.asset_strategies[0].reasoning == "technical-only fallback (LLM unavailable)"
    assert content.asset_strategies[0].confidence == 60
    assert repo.list_performance_logs()


def test_report_adds_screened_non_owned_candidates_with_null_asset_id():
    repo = seeded_repo()
    service = ReportService(
        repo,
        market_data_service=FakeMarketData(),
        technical_analysis_service=FakeTechnical(),
        ai_provider=FailingAI(),
        news_service=FakeNews(),
    )

    report = service.generate_report("domestic")
    content = ReportContent.model_validate(report["content"])
    candidate_tickers = [
        strategy.ticker for strategy in content.asset_strategies if strategy.ticker != "005930"
    ]
    saved_candidate_rows = [
        row
        for row in repo.list_strategies(report["id"])
        if row["ticker"] in candidate_tickers and row.get("asset_id") is None
    ]

    assert candidate_tickers
    assert len(content.asset_strategies) <= 1 + 5
    assert saved_candidate_rows


def test_report_uses_configured_candidate_assets_before_default_universe():
    repo = seeded_repo()
    repo.create_candidate_asset(
        {
            "market": "KR",
            "ticker": "035420",
            "name": "NAVER",
            "currency": "KRW",
            "is_active": True,
        }
    )
    service = ReportService(
        repo,
        market_data_service=FakeMarketData(),
        technical_analysis_service=FakeTechnical(),
        ai_provider=FailingAI(),
        news_service=FakeNews(),
    )

    report = service.generate_report("domestic")
    content = ReportContent.model_validate(report["content"])
    candidate_tickers = [
        strategy.ticker for strategy in content.asset_strategies if strategy.ticker != "005930"
    ]

    assert candidate_tickers == ["035420"]


def test_report_passes_news_context_to_openai():
    repo = seeded_repo()
    ai = RetryAI()
    news = FakeNews()
    service = ReportService(
        repo,
        market_data_service=FakeMarketData(),
        technical_analysis_service=FakeTechnical(),
        ai_provider=ai,
        news_service=news,
    )

    service.generate_report("domestic")

    assert news.calls
    assert ai.contexts[-1]["news_context"]["provider"] == "gdelt_doc_2_0"
    assert (
        ai.contexts[-1]["news_context"]["articles"][0]["title"] == "Semiconductor demand improves"
    )


def test_report_marks_news_context_in_macro_factors():
    repo = seeded_repo()
    ai = RetryAI()
    service = ReportService(
        repo,
        market_data_service=FakeMarketData(),
        technical_analysis_service=FakeTechnical(),
        ai_provider=ai,
        news_service=FakeNews(),
    )

    report = service.generate_report("domestic")
    content = ReportContent.model_validate(report["content"])

    assert any("GDELT" in factor for factor in content.market_summary.macro_factors)


def test_report_generation_refreshes_usd_krw_rate_setting():
    repo = seeded_repo()
    service = ReportService(
        repo,
        market_data_service=FakeMarketDataWithFx(),
        technical_analysis_service=FakeTechnical(),
        ai_provider=FailingAI(),
        news_service=FakeNews(),
    )

    service.generate_report("domestic")

    assert repo.get_settings()["usd_krw_rate"] == 1450


def test_validation_failure_retries_openai_once():
    repo = seeded_repo()
    ai = RetryAI()
    service = ReportService(
        repo,
        market_data_service=FakeMarketData(),
        technical_analysis_service=FakeTechnical(),
        ai_provider=ai,
        news_service=FakeNews(),
    )

    report = service.generate_report("domestic")
    content = ReportContent.model_validate(report["content"])

    assert ai.calls == 2
    assert content.market_summary.summary == "validated report"
    assert content.asset_strategies[0].ticker == "005930"


def test_backfill_performance_logs_updates_trading_day_returns():
    repo = InMemoryRepository()
    strategy = repo.create_strategy(
        {
            "report_id": "report-1",
            "ticker": "AAPL",
            "name": "Apple",
            "action": "HOLD",
            "confidence": 50,
            "current_price": 100,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    )
    log_row = repo.create_performance_log(
        {
            "strategy_id": strategy["id"],
            "ticker": "AAPL",
            "action": "HOLD",
            "price_at_recommendation": 100,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
    )
    service = ReportService(
        repo,
        market_data_service=FakeMarketData(),
        technical_analysis_service=FakeTechnical(),
        ai_provider=FailingAI(),
        news_service=FakeNews(),
    )

    service.backfill_performance_logs()

    updated = next(row for row in repo.list_performance_logs() if row["id"] == log_row["id"])
    assert updated["price_after_1d"] == 51
    assert updated["return_after_1d"] == -49
    assert updated["price_after_5d"] == 55
    assert updated["return_after_5d"] == -45
    assert updated["price_after_20d"] == 70
    assert updated["return_after_20d"] == -30
    assert updated["evaluated_at"]


def test_infer_market_treats_alphanumeric_six_character_codes_as_kr():
    service = ReportService(
        InMemoryRepository(),
        market_data_service=FakeMarketData(),
        technical_analysis_service=FakeTechnical(),
        ai_provider=FailingAI(),
        news_service=FakeNews(),
    )

    assert service._infer_market("0183J0") == "KR"
    assert service._infer_market("AAPL") == "US"
