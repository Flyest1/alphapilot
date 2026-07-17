from types import SimpleNamespace

from app.db.supabase_client import InMemoryRepository
from app.models.advisory import parse_advisory_job_request
from app.services.advisory.pipeline import AdvisoryPipeline


class FakeMarketData:
    def _yf_module(self):
        return FakeYFinance()


class FakeYFinance:
    pass


class FakeNewsService:
    def fetch_report_context(self, report_type, assets):
        assert report_type == "global"
        return {
            "provider": "gdelt_doc_2_0",
            "status": "ok",
            "generated_at": "2026-07-17T00:00:00+00:00",
            "articles": [
                {
                    "title": "Market context",
                    "url": "https://example.com/context",
                    "published_at": "2026-07-16T12:00:00+00:00",
                    "asset_ticker": assets[0]["ticker"] if assets else None,
                }
            ],
        }


def test_pipeline_registers_all_eight_analysis_types():
    pipeline = AdvisoryPipeline(InMemoryRepository(), FakeMarketData(), yf_module=FakeYFinance())

    assert set(pipeline.handlers()) == {
        "undervalued_us_stocks",
        "etf_rebalancing",
        "post_earnings_opportunities",
        "ai_beneficiaries",
        "high_dividend_etfs",
        "sec_filing_risk",
        "etf_overlap",
        "sector_outlook",
    }


def test_pipeline_uses_owned_etfs_when_request_has_no_positions():
    repository = InMemoryRepository()
    repository.create_asset(
        {
            "market": "ETF",
            "ticker": "SPY",
            "name": "SPY",
            "quantity": 1,
            "avg_price": 100,
            "currency": "USD",
        }
    )
    pipeline = AdvisoryPipeline(repository, FakeMarketData(), yf_module=FakeYFinance())

    positions = pipeline._positions(SimpleNamespace(positions=[]))

    assert positions == [{"ticker": "SPY", "weight_pct": 100.0}]


def test_pipeline_prepares_traceable_result_metadata():
    result = {
        "analysis_type": "sector_outlook",
        "evidence": [{"provider": "yfinance", "as_of": "2026-07-16"}],
    }

    AdvisoryPipeline._prepare_result(result)

    assert result["evidence"][0]["evidence_id"] == "sector_outlook:yfinance:1"
    assert result["data_quality"]["providers"] == ["yfinance"]
    assert result["data_quality"]["source_as_of"] == "2026-07-16"
    assert "자동매매" in result["disclaimer"]


def test_pipeline_marks_ai_narrative_as_not_configured():
    pipeline = AdvisoryPipeline(InMemoryRepository(), FakeMarketData(), yf_module=FakeYFinance())
    result = {
        "analysis_type": "sector_outlook",
        "evidence": [{"provider": "yfinance", "as_of": "2026-07-16"}],
        "data_quality": {},
    }

    pipeline._add_narrative(result)

    assert result["ai_narrative"] is None
    assert result["ai_narrative_status"] == {
        "status": "unavailable",
        "reason": "not_configured",
        "provider": "openai",
    }


def test_pipeline_attaches_gdelt_articles_as_evidence():
    pipeline = AdvisoryPipeline(
        InMemoryRepository(),
        FakeMarketData(),
        yf_module=FakeYFinance(),
        news_service=FakeNewsService(),
    )
    result = {"analysis_type": "sector_outlook", "data_quality": {}}

    pipeline._attach_news_context(result, ["AAPL"])
    pipeline._prepare_result(result)

    assert result["news_context"]["status"] == "ok"
    assert result["evidence"][0]["provider"] == "gdelt_doc_2_0"
    assert result["evidence"][0]["evidence_id"].startswith("sector_outlook:gdelt_doc_2_0")


def test_pipeline_passes_current_etf_weights_to_rebalancing(monkeypatch):
    captured = {}

    class FakeRebalancingService:
        def __init__(self, *_args):
            pass

        def analyze(self, positions):
            captured["positions"] = positions
            return {"analysis_type": "etf_rebalancing", "evidence": [], "data_quality": {}}

    monkeypatch.setattr(
        "app.services.advisory.pipeline.EtfRebalancingService",
        FakeRebalancingService,
    )
    pipeline = AdvisoryPipeline(InMemoryRepository(), FakeMarketData(), yf_module=FakeYFinance())
    request = parse_advisory_job_request(
        {
            "analysis_type": "etf_rebalancing",
            "positions": [{"ticker": "VOO", "weight_pct": 60.0}],
        }
    )

    pipeline._etf_rebalancing(None, request)

    assert captured["positions"] == [{"ticker": "VOO", "weight_pct": 60.0}]


def test_pipeline_fills_blank_requested_etf_weights_equally():
    pipeline = AdvisoryPipeline(InMemoryRepository(), FakeMarketData(), yf_module=FakeYFinance())
    request = parse_advisory_job_request(
        {
            "analysis_type": "etf_overlap",
            "positions": [{"ticker": "VOO"}, {"ticker": "QQQ"}, {"ticker": "SCHD"}],
        }
    )

    positions = pipeline._positions(request)

    assert positions == [
        {"ticker": "VOO", "weight_pct": 33.33},
        {"ticker": "QQQ", "weight_pct": 33.33},
        {"ticker": "SCHD", "weight_pct": 33.34},
    ]


def test_sector_market_input_coverage_marks_unavailable_macro_inputs():
    result = {
        "sectors": [{"data_quality": "fresh"}],
        "news_context": {
            "status": "ok",
            "provider": "gdelt_doc_2_0",
            "articles": [{"title": "Fed"}],
        },
    }

    coverage = AdvisoryPipeline._sector_market_input_coverage(result)

    assert coverage["price_trend"]["status"] == "available"
    assert coverage["recent_news"]["article_count"] == 1
    assert coverage["interest_rate_outlook"]["status"] == "data-limited"
    assert coverage["corporate_earnings"]["status"] == "data-limited"
    assert coverage["etf_flows"]["status"] == "data-limited"
