from types import SimpleNamespace

from app.db.supabase_client import InMemoryRepository
from app.models.advisory import parse_advisory_job_request
from app.services.advisory.pipeline import AdvisoryPipeline, PROFIT_TAKING_EVENT_WINDOW_DAYS


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


def test_pipeline_registers_all_ten_analysis_types():
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
        "profit_taking_review",
        "high_upside_speculative_stocks",
    }


def test_pipeline_discovers_speculative_tickers_with_yfinance_screener(monkeypatch):
    captured = {}

    class ScreeningYFinance:
        @staticmethod
        def screen(name, count):
            captured["screen"] = (name, count)
            return {"quotes": [{"symbol": "BIOX", "quoteType": "EQUITY"}]}

    class FakeAnalyzer:
        def __init__(self, *_args, **_kwargs):
            pass

        def analyze(self, tickers, limit):
            captured["analyze"] = (tickers, limit)
            return {
                "analysis_type": "high_upside_speculative_stocks",
                "rows": [],
                "top_candidates": [],
                "speculative_watch": [],
                "rejected_or_data_limited": [],
                "screening_scope": {},
                "scoring_methodology": {},
                "evidence": [],
                "data_quality": {},
                "disclaimer": "정보 제공",
            }

    monkeypatch.setattr(
        "app.services.advisory.pipeline.HighUpsideSpeculativeStocksAnalyzer", FakeAnalyzer
    )
    pipeline = AdvisoryPipeline(
        InMemoryRepository(), FakeMarketData(), yf_module=ScreeningYFinance()
    )
    request = parse_advisory_job_request(
        {"analysis_type": "high_upside_speculative_stocks", "max_results": 5}
    )

    result = pipeline._high_upside_speculative_stocks(None, request)

    assert captured == {"screen": ("aggressive_small_caps", 25), "analyze": (["BIOX"], 5)}
    assert result["screening_scope"]["source"] == "yfinance_aggressive_small_caps"


def test_profit_taking_event_windows_follow_review_horizon():
    assert PROFIT_TAKING_EVENT_WINDOW_DAYS == {"short": 30, "medium": 90, "long": 180}


def test_pipeline_compares_profit_taking_review_with_market_specific_report_type():
    class ReportRepository(InMemoryRepository):
        def __init__(self):
            super().__init__()
            self.report_types = []

        def get_latest_report(self, report_type=None):
            self.report_types.append(report_type)
            return {
                "created_at": "2026-07-30T00:00:00+00:00",
                "content": {
                    "asset_strategies": [{"ticker": "EXM", "action": "BUY", "confidence": 70}]
                },
            }

    repository = ReportRepository()
    pipeline = AdvisoryPipeline(repository, FakeMarketData(), yf_module=FakeYFinance())

    domestic = pipeline._latest_report_strategy({"market": "KR", "ticker": "EXM"})
    global_report = pipeline._latest_report_strategy({"market": "ETF", "ticker": "EXM"})

    assert repository.report_types == ["domestic", "global"]
    assert domestic["action"] == "BUY"
    assert global_report["action"] == "BUY"


def test_profit_taking_context_uses_usd_rate_when_us_asset_currency_is_missing(monkeypatch):
    class FakePortfolioService:
        def __init__(self, *_args):
            pass

        def get_summary(self):
            return SimpleNamespace(total_market_value=100000, usd_krw_rate=1400)

    monkeypatch.setattr(
        "app.services.advisory.pipeline.PortfolioService",
        FakePortfolioService,
    )
    pipeline = AdvisoryPipeline(InMemoryRepository(), FakeMarketData(), yf_module=FakeYFinance())

    context = pipeline._profit_taking_context(
        {"id": "asset-us", "market": "US", "ticker": "AAPL", "currency": None}
    )

    assert context["currency_fx_rate"] == 1400


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


def test_pipeline_repairs_blank_duplicate_evidence_metadata():
    result = {
        "analysis_type": "etf_overlap",
        "evidence": [
            {
                "evidence_id": "",
                "provider": "",
                "last_trading_date": "2026-07-16",
            },
            {
                "evidence_id": "etf-overlap-source",
                "provider": "yfinance",
                "last_trading_date": "2026-07-15",
            },
            {
                "evidence_id": "etf-overlap-source",
                "provider": "yfinance",
                "last_trading_date": "2026-07-14",
            },
        ],
    }

    AdvisoryPipeline._prepare_result(result)

    assert [item["evidence_id"] for item in result["evidence"]] == [
        "etf_overlap:unknown:1",
        "etf-overlap-source",
        "etf_overlap:yfinance:3",
    ]
    assert result["evidence"][0]["provider"] == "unknown"
    assert result["evidence"][0]["as_of"] == "2026-07-16"
    assert result["data_quality"]["source_as_of"] == "2026-07-16"


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


def test_pipeline_passes_ai_themes_to_analyzer(monkeypatch):
    captured = {}

    class FakeAnalyzer:
        def __init__(self, *_args, **_kwargs):
            pass

        def analyze(self, tickers, themes):
            captured["tickers"] = tickers
            captured["themes"] = themes
            return {
                "analysis_type": "ai_beneficiaries",
                "rows": [],
                "verified_ai_beneficiaries": [],
                "ai_theme_caution": [],
                "evidence": [],
                "data_quality": {},
                "disclaimer": "투자 의사결정 지원 정보입니다.",
            }

    monkeypatch.setattr(
        "app.services.advisory.pipeline.AIBeneficiariesAnalyzer",
        FakeAnalyzer,
    )
    repository = InMemoryRepository()
    repository.upsert_candidate_universe(
        {
            "report_type": "global",
            "market": "US",
            "ticker": "NVDA",
            "name": "NVIDIA",
            "currency": "USD",
            "source_rank": 1,
        }
    )
    pipeline = AdvisoryPipeline(repository, FakeMarketData(), yf_module=FakeYFinance())
    request = parse_advisory_job_request(
        {"analysis_type": "ai_beneficiaries", "themes": ["inference", "software"]}
    )

    pipeline._ai_beneficiaries(None, request)

    assert captured == {
        "tickers": ["NVDA"],
        "themes": ["inference", "software"],
    }


def test_pipeline_passes_sec_lookback_to_analyzer(monkeypatch):
    captured = {}

    class FakeAnalyzer:
        def __init__(self, *_args):
            pass

        def analyze(self, ticker, lookback_days):
            captured["ticker"] = ticker
            captured["lookback_days"] = lookback_days
            return {
                "analysis_type": "sec_filing_risk",
                "ticker": ticker,
                "latest_filings": [],
                "newly_emphasized_risks": [],
                "risk_categories": [],
                "management_caution_signals": [],
                "key_sentences": [],
                "risk_rating": "insufficient_data",
                "evaluation_status": "unavailable",
                "rating_reason": "근거 부족",
                "evidence": [],
                "data_quality": {},
                "disclaimer": "투자 의사결정 지원 정보입니다.",
            }

    monkeypatch.setattr(
        "app.services.advisory.pipeline.SECFilingRiskAnalyzer",
        FakeAnalyzer,
    )
    pipeline = AdvisoryPipeline(InMemoryRepository(), FakeMarketData(), yf_module=FakeYFinance())
    request = parse_advisory_job_request(
        {
            "analysis_type": "sec_filing_risk",
            "ticker": "AAPL",
            "lookback_days": 180,
        }
    )

    pipeline._sec_filing_risk(None, request)

    assert captured == {"ticker": "AAPL", "lookback_days": 180}


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
