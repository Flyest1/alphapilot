"""Phase 5-3: 리포트 파이프라인의 신규 후보 제안 투입 한도."""

from datetime import datetime, timezone

import pandas as pd

from app.db.supabase_client import InMemoryRepository
from app.models.report import ReportContent
from app.services.market_data_service import MarketDataResult
from app.services.report_service import ReportService
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
    def fetch_price_history(self, *_args, **_kwargs):
        return MarketDataResult(
            dataframe=market_frame(),
            last_trading_date=datetime(2026, 6, 30, tzinfo=timezone.utc),
            is_stale=False,
            provider="mock",
            data_quality_note="ok",
            current_price=179,
        )

    def fetch_major_indices(self, report_type, **_kwargs):
        return {"KOSPI" if report_type == "domestic" else "S&P 500": self.fetch_price_history()}


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
        return {"provider": "gdelt_doc_2_0", "status": "empty", "articles": [], "queries": []}


def build_service(repo):
    return ReportService(
        repo,
        market_data_service=FakeMarketData(),
        technical_analysis_service=FakeTechnical(),
        ai_provider=FailingAI(),
        news_service=FakeNews(),
    )


def seeded_repo(cash=1_000_000):
    repo = InMemoryRepository()
    repo.upsert_settings({"usd_krw_rate": 1000, "risk_per_trade_pct": 1.0})
    repo.create_asset(
        {
            "market": "KR",
            "ticker": "005930",
            "name": "Samsung",
            "quantity": 1,
            "avg_price": 1_000_000,
            "currency": "KRW",
        }
    )
    if cash:
        repo.create_asset(
            {
                "market": "CASH",
                "ticker": "KRW",
                "name": "현금",
                "quantity": 1,
                "avg_price": cash,
                "currency": "KRW",
            }
        )
    return repo


def test_candidates_receive_position_sizing_amount_range():
    repo = seeded_repo()
    report = build_service(repo).generate_report("domestic")
    content = ReportContent.model_validate(report["content"])

    candidates = [s for s in content.asset_strategies if s.ticker != "005930"]
    owned = next(s for s in content.asset_strategies if s.ticker == "005930")
    sized = [s for s in candidates if s.position_sizing]

    assert sized, "후보 전략에 제안 투입 한도가 있어야 합니다"
    sizing = sized[0].position_sizing
    # 현금 1,000,000 × 균형 성향 비율 0.2 = 200,000
    assert sizing["cash_cap_amount"] == 200000
    # 리스크 한도 = 총 평가액(현금 + 시세 기준 보유분) × 1%
    assert sizing["risk_budget_amount"] > 0
    assert sizing["risk_cap_amount"] > sizing["risk_budget_amount"]
    assert sizing["suggested_max_amount"] == min(
        sizing["risk_cap_amount"], sizing["cash_cap_amount"]
    )
    assert sizing["currency"] == "KRW"
    assert sizing["method"] == "fixed-fractional"
    # 보유 자산에는 사이징을 제공하지 않는다
    assert owned.position_sizing is None


def test_no_position_sizing_without_cash():
    repo = seeded_repo(cash=0)
    report = build_service(repo).generate_report("domestic")
    content = ReportContent.model_validate(report["content"])

    assert all(s.position_sizing is None for s in content.asset_strategies)
