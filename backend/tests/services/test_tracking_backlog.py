from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd

from app.db.supabase_client import InMemoryRepository
from app.services.report.tracking import PerformanceTracker


class History:
    def __init__(self, start="2020-01-01"):
        self.frame = pd.DataFrame(
            {"close": range(100, 181)}, index=pd.bdate_range(start, periods=81)
        )
        self.lookbacks = []

    def fetch_price_history(self, market, ticker, lookback_days):
        self.lookbacks.append(lookback_days)
        return SimpleNamespace(dataframe=self.frame)


def test_cycle_backfill_reaches_older_rows_beyond_500_stalled_rows():
    repo = InMemoryRepository()
    oldest = repo.create_recommendation_cycle(
        {
            "ticker": "AAPL",
            "started_at": "2020-01-01",
            "created_at": "2020-01-01",
            "reference_price": 100,
            "status": "active",
        }
    )
    for _ in range(501):
        repo.create_recommendation_cycle({"ticker": "", "status": "active"})
    PerformanceTracker(repo, History()).backfill_recommendation_cycles()
    assert repo.recommendation_cycles[oldest["id"]]["price_after_60d"] == 160


def test_log_backfill_reaches_older_rows_beyond_250_stalled_rows():
    repo = InMemoryRepository()
    strategy = repo.create_strategy({"ticker": "AAPL", "created_at": "2020-01-01"})
    oldest = repo.create_performance_log(
        {"strategy_id": strategy["id"], "created_at": "2020-01-01", "price_at_recommendation": 100}
    )
    for _ in range(251):
        repo.create_performance_log({"strategy_id": "missing"})
    PerformanceTracker(repo, History()).backfill_performance_logs()
    assert repo.performance_logs[oldest["id"]]["price_after_20d"] == 120


def test_failed_log_does_not_abort_remaining_rows():
    repo = InMemoryRepository()
    strategy = repo.create_strategy({"ticker": "AAPL", "created_at": "2020-01-01"})
    good = repo.create_performance_log(
        {"strategy_id": strategy["id"], "created_at": "2020-01-01", "price_at_recommendation": 100}
    )
    repo.create_performance_log({"strategy_id": strategy["id"], "price_at_recommendation": "bad"})
    PerformanceTracker(repo, History()).backfill_performance_logs()
    assert repo.performance_logs[good["id"]]["price_after_20d"] == 120


def test_old_log_requests_history_covering_recommendation_date():
    repo = InMemoryRepository()
    strategy = repo.create_strategy({"ticker": "AAPL", "created_at": "2020-01-01"})
    repo.create_performance_log({"strategy_id": strategy["id"], "price_at_recommendation": 100})
    history = History()
    PerformanceTracker(repo, history).backfill_performance_logs()
    assert (
        history.lookbacks[0]
        >= (datetime.now(timezone.utc).date() - datetime(2020, 1, 1).date()).days
    )


def test_truncated_history_is_not_relabeled_as_first_forward_trading_day(caplog):
    repo = InMemoryRepository()
    strategy = repo.create_strategy({"ticker": "AAPL", "created_at": "2020-01-01"})
    log = repo.create_performance_log(
        {"strategy_id": strategy["id"], "price_at_recommendation": 100}
    )
    PerformanceTracker(repo, History("2021-01-01")).backfill_performance_logs()
    assert repo.performance_logs[log["id"]].get("price_after_1d") is None
    assert "missing_recommendation_history_anchor" in caplog.text


def test_truncated_cycle_history_preserves_prior_outcome_and_returns(caplog):
    repo = InMemoryRepository()
    cycle = repo.create_recommendation_cycle(
        {
            "ticker": "AAPL",
            "started_at": "2020-01-01",
            "reference_price": 100,
            "status": "hit_stop",
            "price_after_1d": 95,
            "stop_loss": 96,
            "closed_at": "2020-01-02",
        }
    )
    tracker = PerformanceTracker(repo, History("2021-01-01"))
    tracker.backfill_recommendation_cycles()
    assert tracker.recalculate_recommendation_cycles() == 0
    updated = repo.recommendation_cycles[cycle["id"]]
    assert updated["status"] == "hit_stop"
    assert updated["price_after_1d"] == 95
    assert updated["closed_at"] == "2020-01-02"
    assert updated.get("price_after_60d") is None
    assert "missing_recommendation_history_anchor" in caplog.text
