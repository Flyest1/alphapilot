import pandas as pd

from app.db.supabase_client import InMemoryRepository
from app.services.backtest_service import RuleBacktestService, action_for_score
from app.services.market_data_service import MarketDataResult


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


def test_action_for_score_matches_documented_bands():
    assert action_for_score(80) == "BUY"
    assert action_for_score(65) == "WATCH"
    assert action_for_score(40) == "REDUCE"
    assert action_for_score(20) == "SELL"


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
