import pandas as pd
import pytest
from types import SimpleNamespace

from app.db.supabase_client import InMemoryRepository
from app.services.backtest_service import RuleBacktestService, action_for_score
from app.services.market_data_service import MarketDataResult
from app.services.strategy_service import StrategyService


class FakeMarketData:
    def fetch_price_history(self, *_args, **_kwargs):
        index = pd.date_range("2024-01-01", periods=180, freq="B")
        values = pd.Series(range(100, 280), index=index, dtype=float)
        frame = pd.DataFrame(
            {
                "open": values,
                "high": values + 1,
                "low": values - 1,
                "close": values,
                "volume": values * 10,
            },
            index=index,
        )
        return MarketDataResult(frame, None, False, "mock", "ok", float(values.iloc[-1]))


@pytest.mark.parametrize("risk_profile", ["conservative", "balanced", "aggressive"])
@pytest.mark.parametrize("score", [34, 35, 49, 50, 64, 65, 79, 80])
def test_action_for_score_matches_operational_mapping(risk_profile, score):
    assert action_for_score(score, risk_profile) == StrategyService.action_for_score(
        score, risk_profile
    )


def test_rule_backtest_returns_reproducible_simulation_groups():
    repository = InMemoryRepository()
    repository.upsert_candidate_universe(
        {
            "report_type": "global",
            "market": "US",
            "ticker": "AAPL",
            "name": "Apple",
            "currency": "USD",
            "source": "test",
        }
    )

    result = RuleBacktestService(repository, FakeMarketData()).run("global")

    assert result["tickers_tested"] == ["AAPL"]
    assert result["sample_count"] > 0
    assert result["groups"]
    assert all(group["avg_forward_return"] > 0 for group in result["groups"])
    assert "시뮬레이션" in result["disclaimer"]


def test_rule_backtest_uses_saved_risk_profile():
    repository = InMemoryRepository()
    repository.upsert_settings({"risk_profile": "aggressive", "candidate_horizon": "short"})
    repository.upsert_candidate_universe(
        {
            "report_type": "global",
            "market": "US",
            "ticker": "AAPL",
            "name": "Apple",
            "currency": "USD",
            "source": "test",
        }
    )

    class FixedTechnicalAnalysis:
        def analyze(self, *_args, **_kwargs):
            return SimpleNamespace(technical_score=70)

    service = RuleBacktestService(
        repository,
        FakeMarketData(),
        technical_analysis_service=FixedTechnicalAnalysis(),
    )

    result = service.run("global", limit=1)

    assert [group["action"] for group in result["groups"]] == ["BUY"]
    assert result["forward_days"] == 5
