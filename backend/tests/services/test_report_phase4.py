"""Phase 4 통합 동작: 신뢰도 보정, report_inputs 스냅샷, 섹터 자동 보충."""

from datetime import datetime, timezone

import pandas as pd

from app.db.supabase_client import InMemoryRepository
from app.models.report import AssetStrategy, ReportContent
from app.services.market_data_service import MarketDataResult
from app.services.report.persistence import ReportPersistence
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
    def __init__(self, sector=None):
        self.frame = market_frame()
        self.sector = sector
        self.sector_calls = []

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

    def fetch_sector(self, market, ticker):
        self.sector_calls.append((market, ticker))
        return self.sector


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


class FakeNews:
    def fetch_report_context(self, _report_type, _assets):
        return {
            "provider": "gdelt_doc_2_0",
            "status": "ok",
            "generated_at": "2026-07-12T00:00:00+00:00",
            "timespan": "3d",
            "articles": [
                {
                    "query": "mock",
                    "query_scope": "asset",
                    "asset_ticker": "005930",
                    "asset_name": "Samsung",
                    "title": "mock",
                    "url": "https://example.com",
                    "domain": "example.com",
                    "seen_at": "2026-07-11T00:00:00+00:00",
                    "collected_at": "2026-07-12T00:00:00+00:00",
                    "evidence_level": "headline-only",
                }
            ],
            "queries": ["mock"],
            "query_details": [{"query": "mock", "scope": "asset", "ticker": "005930"}],
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


def build_service(repo, market_data=None):
    return ReportService(
        repo,
        market_data_service=market_data or FakeMarketData(),
        technical_analysis_service=FakeTechnical(),
        ai_provider=FailingAI(),
        news_service=FakeNews(),
    )


def seed_closed_cycles(
    repo,
    count,
    wins,
    confidence,
    action="HOLD",
    horizon="medium",
    technical_score=None,
):
    for index in range(count):
        repo.create_recommendation_cycle(
            {
                "report_type": "domestic",
                "ticker": f"SEED{index:03d}",
                "name": "seed",
                "action": action,
                "horizon": horizon,
                "status": "hit_target" if index < wins else "hit_stop",
                "reference_price": 100,
                "technical_score": technical_score if technical_score is not None else confidence,
                "base_confidence": confidence,
                "calibrated_confidence": confidence,
                "metadata": {},
                "started_at": "2025-01-01T00:00:00+00:00",
                "closed_at": "2025-01-20T00:00:00+00:00",
            }
        )


def test_generate_report_attaches_confidence_detail_without_samples():
    repo = seeded_repo()
    report = build_service(repo).generate_report("domestic")
    content = ReportContent.model_validate(report["content"])

    owned = next(s for s in content.asset_strategies if s.ticker == "005930")
    assert owned.confidence == 60  # 폴백 캡 유지 (보정 표본 없음)
    assert owned.confidence_detail["calibrated"] is False
    assert owned.confidence_detail["news_context_used"] is False
    assert owned.confidence_detail["technical_confidence"] == 60


def test_generate_report_calibrates_confidence_with_enough_samples():
    repo = seeded_repo()
    # 폴백 리포트에서 보유 전략은 BUY(점수 85)·confidence 60 캡(60s 밴드)이 된다.
    seed_closed_cycles(
        repo,
        count=30,
        wins=24,
        confidence=60,
        action="BUY",
        technical_score=85,
    )

    report = build_service(repo).generate_report("domestic")
    content = ReportContent.model_validate(report["content"])

    owned = next(s for s in content.asset_strategies if s.ticker == "005930")
    assert owned.confidence == 60
    assert owned.confidence_detail["calibrated"] is True
    assert owned.confidence_detail["sample_size"] == 30
    assert owned.confidence_detail["calibration_factor"] == 1.3


def test_generate_report_saves_report_inputs_snapshot():
    repo = seeded_repo()
    report = build_service(repo).generate_report("domestic")

    saved = repo.get_report(report["id"])
    inputs = saved["report_inputs"]
    assert inputs["tickers"]["005930"]["provider"] == "mock"
    assert inputs["tickers"]["005930"]["is_stale"] is False
    assert inputs["tickers"]["005930"]["technical_score"] == 85
    assert inputs["news_context"]["status"] == "ok"
    assert inputs["news_context"]["article_count"] == 1
    assert inputs["news_context"]["news_context_used"] is False
    assert inputs["news_context"]["news_contribution_score"] == 0.0
    assert inputs["news_context"]["news_contribution_mode"] == "not_modeled"
    assert inputs["news_context"]["evidence_mode"] == "headline-only"
    assert inputs["news_context"]["queries"][0]["ticker"] == "005930"
    assert inputs["news_context"]["articles"][0]["domain"] == "example.com"
    assert inputs["news_context"]["articles"][0]["evidence_id"] == "N1"
    assert inputs["news_context"]["articles"][0]["seen_at"] == "2026-07-11T00:00:00+00:00"
    assert inputs["news_context"]["used_evidence_ids"] == []
    assert inputs["settings"]["candidate_horizon"] == "medium"


def test_news_snapshot_links_cited_evidence_to_output_path():
    repo = seeded_repo()
    service = build_service(repo)
    report = service.generate_report("domestic")
    content = ReportContent.model_validate(report["content"])
    content = content.model_copy(
        update={
            "market_summary": content.market_summary.model_copy(
                update={"summary": "뉴스 근거를 확인했습니다 [[N1]]."}
            )
        }
    )
    news_context = FakeNews().fetch_report_context("domestic", [])
    news_context["articles"][0]["evidence_id"] = "N1"

    snapshot = service._news_input_snapshot(news_context, content)

    assert snapshot["used_evidence_ids"] == ["N1"]
    assert snapshot["evidence_usage"] == [
        {"evidence_id": "N1", "output_path": "market_summary.summary"}
    ]
    assert snapshot["news_context_used"] is True

    uncited_content = content.model_copy(
        update={
            "market_summary": content.market_summary.model_copy(
                update={"summary": "마커 없이 서술한 문장입니다."}
            )
        }
    )
    uncited_snapshot = service._news_input_snapshot(news_context, uncited_content)
    assert uncited_snapshot["news_context_used"] is False


def test_confidence_detail_marks_only_strategy_level_news_citations_as_used():
    repo = seeded_repo()
    service = build_service(repo)
    report = service.generate_report("domestic")
    content = ReportContent.model_validate(report["content"])
    cited_strategy = content.asset_strategies[0].model_copy(
        update={"reasoning": "헤드라인 근거를 참고했습니다 [[N1]]."}
    )
    content = content.model_copy(update={"asset_strategies": [cited_strategy]})
    news_context = FakeNews().fetch_report_context("domestic", [])
    news_context["articles"][0]["evidence_id"] = "N1"

    calibrated = service._apply_confidence_calibration(
        content,
        "medium",
        news_context,
        analysis_rows=[],
    )

    assert calibrated.asset_strategies[0].confidence_detail["news_context_used"] is True


def test_report_inputs_fallback_only_matches_missing_column_errors():
    persistence = ReportPersistence(InMemoryRepository())

    assert persistence._is_missing_report_inputs_column(
        RuntimeError("Could not find the 'report_inputs' column in the schema cache")
    )
    assert not persistence._is_missing_report_inputs_column(RuntimeError("database unavailable"))
    assert not persistence._is_missing_report_inputs_column(
        RuntimeError("report_inputs column write failed because the database is unavailable")
    )


def test_generate_report_saves_separate_cycle_score_fields():
    repo = seeded_repo()
    build_service(repo).generate_report("domestic")

    cycle = next(row for row in repo.list_recommendation_cycles() if row["ticker"] == "005930")

    assert cycle["technical_score"] == 85
    assert cycle["base_confidence"] == 60
    assert cycle["calibrated_confidence"] == 60
    assert cycle["metadata"]["technical_score"] == 85


def test_reused_cycle_preserves_initial_score_fields():
    repository = InMemoryRepository()
    report = repository.create_report(
        {"report_type": "global", "title": "report", "summary": "summary", "content": {}}
    )
    persistence = ReportPersistence(repository)
    existing_cycles = []
    first = AssetStrategy(
        ticker="AAPL",
        name="Apple",
        current_price=100,
        action="BUY",
        confidence=70,
        target_price=110,
        stop_loss=90,
        reasoning="first",
        risk="risk",
        invalidation_condition="condition",
        confidence_detail={"base_confidence": 70},
    )
    first_row = repository.create_strategy(
        {"report_id": report["id"], "ticker": "AAPL", "action": "BUY"}
    )
    persistence.sync_recommendation_cycle(
        first, first_row, report, "medium", existing_cycles, technical_score=80
    )
    second = first.model_copy(
        update={
            "confidence": 90,
            "target_price": 112,
            "stop_loss": 91,
            "confidence_detail": {"base_confidence": 88},
        }
    )
    second_row = repository.create_strategy(
        {"report_id": report["id"], "ticker": "AAPL", "action": "BUY"}
    )

    persistence.sync_recommendation_cycle(
        second, second_row, report, "medium", existing_cycles, technical_score=95
    )

    cycle = repository.list_recommendation_cycles()[0]
    assert cycle["technical_score"] == 80
    assert cycle["base_confidence"] == 70
    assert cycle["calibrated_confidence"] == 70
    assert cycle["metadata"]["latest_technical_score"] == 95


def test_generate_report_backfills_missing_sector():
    repo = seeded_repo()
    market_data = FakeMarketData(sector="Technology")

    build_service(repo, market_data).generate_report("domestic")

    asset = repo.list_assets()[0]
    assert asset["sector"] == "Technology"
    assert ("KR", "005930") in market_data.sector_calls


def test_generate_report_skips_sector_fetch_when_already_set():
    repo = InMemoryRepository()
    repo.create_asset(
        {
            "market": "KR",
            "ticker": "005930",
            "name": "Samsung",
            "quantity": 1,
            "avg_price": 100,
            "currency": "KRW",
            "sector": "기존섹터",
        }
    )
    market_data = FakeMarketData(sector="Technology")

    build_service(repo, market_data).generate_report("domestic")

    assert repo.list_assets()[0]["sector"] == "기존섹터"
    assert market_data.sector_calls == []


class CitingAI:
    """Emits the marker format the prompt asks for, plus a raw source leak."""

    def generate_report(self, _prompt, context):
        strategy = context["technical_strategies"][0]
        return {
            "report_type": context["report_type"],
            "generated_at": context["generated_at"],
            "market_summary": {
                "summary": "반도체 수요가 개선됐습니다 [[N1]].",
                "key_indices": [],
                "macro_factors": ["example.com 기준 금리는 유지됩니다."],
            },
            "portfolio_summary": {
                "total_market_value": 1.0,
                "total_return_rate": 0.0,
                "risk_level": "medium",
                "allocation_comment": "비중은 유지합니다.",
            },
            "key_risks": ["환율 변동성이 남아 있습니다."],
            "opportunities": ["기술주 반등 여지가 있습니다."],
            "asset_strategies": [
                {
                    **strategy,
                    "reasoning": "헤드라인을 참고했습니다 [[N1]].",
                    "risk": "변동성이 큽니다.",
                    "invalidation_condition": "지지선 이탈 시 무효화합니다.",
                }
            ],
            "disclaimer": DISCLAIMER,
        }


def test_evidence_markers_are_recorded_then_redacted_before_persistence():
    repo = seeded_repo()
    service = ReportService(
        repo,
        market_data_service=FakeMarketData(),
        technical_analysis_service=FakeTechnical(),
        ai_provider=CitingAI(),
        news_service=FakeNews(),
    )
    news_context = FakeNews().fetch_report_context("domestic", [])
    news_context["articles"][0]["evidence_id"] = "N1"

    report = service.generate_report("domestic")
    saved = repo.get_report(report["id"])
    inputs = saved["report_inputs"]

    # Attribution is measured from the marker...
    assert inputs["news_context"]["news_context_used"] is True
    assert inputs["news_context"]["used_evidence_ids"] == ["N1"]
    # ...and the stored narrative carries neither the marker nor the raw domain.
    stored = str(saved["content"])
    assert "[[N1]]" not in stored
    assert "example.com" not in stored
    assert "반도체 수요가 개선됐습니다." in stored
    assert inputs["ai_generation"]["redacted_paths"]
