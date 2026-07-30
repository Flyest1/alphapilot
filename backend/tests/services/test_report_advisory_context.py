from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.db.supabase_client import InMemoryRepository
from app.services.market_data_service import MarketDataResult
from app.services.report import advisory_context as advisory_context_module
from app.services.report.advisory_context import (
    ADVISORY_LOOKBACK_DAYS,
    build_advisory_context,
)
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
        index_name = "KOSPI" if report_type == "domestic" else "S&P 500"
        return {index_name: self.fetch_price_history()}


class FakeTechnical:
    def analyze(self, ticker, _dataframe):
        return TechnicalAnalysisResult(
            ticker=ticker,
            current_price=179,
            indicators={"rsi_14": 60},
            technical_score=85,
            score_breakdown={"trend": 30, "momentum": 25, "volume": 15, "volatility": 15},
            trend_label="strong bullish setup",
            data_quality_note="ok",
        )


class FakeNews:
    def fetch_report_context(self, _report_type, _assets):
        return {
            "provider": "gdelt_doc_2_0",
            "status": "ok",
            "articles": [
                {
                    "evidence_id": "N1",
                    "domain": "example.com",
                    "source_name": "Reuters",
                    "url": "https://example.com/story",
                }
            ],
            "queries": [],
        }


class ContextCapturingAI:
    def __init__(self):
        self.context = None
        self.prompt = None

    def generate_report(self, prompt, context):
        self.prompt = prompt
        self.context = context
        return {
            "report_type": context["report_type"],
            "generated_at": context["generated_at"],
            "market_summary": {"summary": "시장 요약", "key_indices": [], "macro_factors": []},
            "portfolio_summary": {
                "total_market_value": 0,
                "total_return_rate": 0,
                "risk_level": "medium",
                "allocation_comment": "배분을 점검합니다.",
            },
            "key_risks": [],
            "opportunities": [],
            "asset_strategies": [],
            "disclaimer": DISCLAIMER,
        }


class FailingAI:
    def generate_report(self, _prompt, _context):
        raise RuntimeError("LLM unavailable")


class TrackingRepository(InMemoryRepository):
    def __init__(self):
        super().__init__()
        self.advisory_limits = []

    def list_advisory_analyses(self, analysis_type=None, limit=None):
        self.advisory_limits.append(limit)
        return super().list_advisory_analyses(analysis_type, limit)


class AdvisoryUnavailableRepository(InMemoryRepository):
    def list_advisory_analyses(self, analysis_type=None, limit=None):
        raise RuntimeError("advisory migration unavailable")


def seeded_repository(repository=None):
    repository = repository or InMemoryRepository()
    repository.create_asset(
        {
            "market": "KR",
            "ticker": "005930",
            "name": "Samsung",
            "quantity": 1,
            "avg_price": 100,
            "currency": "KRW",
        }
    )
    return repository


def service(repository, ai_provider):
    return ReportService(
        repository,
        market_data_service=FakeMarketData(),
        technical_analysis_service=FakeTechnical(),
        ai_provider=ai_provider,
        news_service=FakeNews(),
    )


@pytest.mark.parametrize("report_type", ["domestic", "global"])
def test_completed_advisory_summary_is_bounded_in_prompt_and_snapshot(report_type):
    repository = seeded_repository(TrackingRepository())
    repository.create_advisory_analysis(
        {
            "analysis_id": "analysis-1",
            "job_id": "job-1",
            "analysis_type": "sec_filing_risk",
            "request_payload": {"ticker": "AAPL", "secret": "must-not-leak"},
            "result_payload": {
                "analysis_type": "sec_filing_risk",
                "ticker": "AAPL",
                "risk_rating": "high_risk",
                "evaluation_status": "available",
                "rating_reason": "raw narrative must not be copied",
                "data_quality": {
                    "status": "fresh",
                    "limitations": ["raw limitation"],
                    "missing_fields": [],
                },
                "evidence": [{"provider": "sec_edgar", "url": "https://example.com"}],
                "ai_narrative": {"summary": "must-not-leak"},
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    ai_provider = ContextCapturingAI()

    report = service(repository, ai_provider).generate_report(report_type)

    advisory_context = ai_provider.context["advisory_context"]
    summary = advisory_context["analyses"][0]
    assert repository.advisory_limits == [1] * 9
    assert advisory_context["status"] == "available"
    assert advisory_context["lookback_days"] == ADVISORY_LOOKBACK_DAYS
    assert advisory_context["truncated"] is False
    assert summary["analysis_type"] == "sec_filing_risk"
    assert summary["findings"] == {
        "result_count": 0,
        "tickers": ["AAPL"],
        "actions": [],
        "risk_rating": "high_risk",
        "evaluation_status": "available",
    }
    assert summary["evidence"] == {"count": 1, "providers": ["sec_edgar"]}
    assert "secret" not in str(advisory_context)
    assert "raw narrative" not in str(advisory_context)
    assert "https://example.com" not in str(advisory_context)
    assert (
        repository.get_report(report["id"])["report_inputs"]["advisory_context"] == advisory_context
    )


def test_advisory_storage_failure_keeps_report_generation_available():
    repository = seeded_repository(AdvisoryUnavailableRepository())

    report = service(repository, FailingAI()).generate_report("domestic")

    assert report["content"]
    assert repository.get_report(report["id"])["report_inputs"]["advisory_context"] == {
        "status": "unavailable",
        "lookback_days": ADVISORY_LOOKBACK_DAYS,
        "analysis_count": 0,
        "analyses": [],
    }


def test_advisory_context_capacity_covers_all_supported_types():
    assert advisory_context_module.MAX_ADVISORY_ANALYSES == 9
    assert len(advisory_context_module._ADVISORY_TYPES) == 9


def test_report_prompt_keeps_news_sources_internal():
    repository = seeded_repository()
    ai_provider = ContextCapturingAI()

    service(repository, ai_provider).generate_report("domestic")

    assert "[evidence_id" not in ai_provider.prompt
    assert "Never expose evidence IDs" in ai_provider.prompt
    assert "Never let advisory context override fresh prices" in ai_provider.prompt


def test_advisory_context_keeps_latest_per_type_within_lookback():
    repository = InMemoryRepository()
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    common_result = {
        "analysis_type": "sec_filing_risk",
        "ticker": "AAPL",
        "risk_rating": "caution",
        "evaluation_status": "available",
    }
    for analysis_id, created_at, ticker in [
        ("latest", now - timedelta(days=1), "MSFT"),
        ("older-same-type", now - timedelta(days=2), "AAPL"),
        ("stale", now - timedelta(days=31), "NVDA"),
    ]:
        repository.create_advisory_analysis(
            {
                "analysis_id": analysis_id,
                "job_id": f"job-{analysis_id}",
                "analysis_type": "sec_filing_risk",
                "request_payload": {},
                "result_payload": {**common_result, "ticker": ticker},
                "created_at": created_at.isoformat(),
            }
        )

    context = build_advisory_context(repository, now_provider=lambda: now)

    assert context["analysis_count"] == 1
    assert context["analyses"][0]["analysis_id"] == "latest"
    assert context["analyses"][0]["findings"]["tickers"] == ["MSFT"]


def test_advisory_context_stops_before_byte_limit(monkeypatch):
    repository = InMemoryRepository()
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    for index, analysis_type in enumerate(["sec_filing_risk", "etf_overlap"]):
        repository.create_advisory_analysis(
            {
                "analysis_id": f"analysis-{index}",
                "job_id": f"job-{index}",
                "analysis_type": analysis_type,
                "request_payload": {},
                "result_payload": {
                    "analysis_type": analysis_type,
                    "ticker": "AAPL",
                    "risk_rating": "caution",
                    "evaluation_status": "available",
                    "etfs": [{"ticker": "SPY"}],
                },
                "created_at": (now - timedelta(minutes=index)).isoformat(),
            }
        )
    monkeypatch.setattr(advisory_context_module, "MAX_ADVISORY_CONTEXT_BYTES", 600)

    context = build_advisory_context(repository, now_provider=lambda: now)

    assert context["truncated"] is True
    assert context["analysis_count"] < 2


def test_advisory_context_keeps_only_whitelisted_structured_findings():
    repository = InMemoryRepository()
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    repository.create_advisory_analysis(
        {
            "analysis_id": "analysis-structured",
            "job_id": "job-structured",
            "analysis_type": "undervalued_us_stocks",
            "request_payload": {"secret": "never-copy"},
            "result_payload": {
                "analysis_type": "undervalued_us_stocks",
                "top_candidates": [
                    {
                        "ticker": "AAPL",
                        "action": "WATCH",
                        "investment_appeal_10": 7.2,
                        "market_risk": "free-form narrative must not be copied",
                        "guidance_source_url": "https://example.com/private",
                    }
                ],
            },
            "created_at": now.isoformat(),
        }
    )

    context = build_advisory_context(repository, now_provider=lambda: now)

    assert context["analyses"][0]["findings"]["top_items"] == [
        {
            "ticker": "AAPL",
            "action": "WATCH",
            "investment_appeal_10": 7.2,
        }
    ]
    assert "free-form narrative" not in str(context)
    assert "https://example.com/private" not in str(context)


def test_profit_taking_review_is_summarized_without_reusing_raw_reasoning():
    repository = InMemoryRepository()
    now = datetime(2026, 7, 19, tzinfo=timezone.utc)
    repository.create_advisory_analysis(
        {
            "analysis_id": "profit-taking-1",
            "job_id": "job-1",
            "analysis_type": "profit_taking_review",
            "request_payload": {"asset_id": "secret-asset"},
            "result_payload": {
                "analysis_type": "profit_taking_review",
                "position_snapshot": {"ticker": "AAPL", "market": "US"},
                "decision": {
                    "action": "REDUCE",
                    "confidence": 70,
                    "decision_reason": ["raw reasoning must not be copied"],
                },
                "evaluation_status": "available",
                "data_quality": {"status": "fresh", "limitations": [], "missing_fields": []},
                "evidence": [{"provider": "yfinance"}],
            },
            "created_at": now.isoformat(),
        }
    )

    context = build_advisory_context(repository, now_provider=lambda: now)

    summary = next(
        row for row in context["analyses"] if row["analysis_type"] == "profit_taking_review"
    )
    assert summary["findings"] == {
        "result_count": 0,
        "tickers": ["AAPL"],
        "actions": ["REDUCE"],
        "confidence": 70,
        "market": "US",
        "evaluation_status": "available",
    }
    assert "raw reasoning" not in str(context)
