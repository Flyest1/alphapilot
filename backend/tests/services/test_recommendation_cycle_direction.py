from datetime import timezone

import pandas as pd
import pytest

from app.db.supabase_client import InMemoryRepository
from app.services.market_data_service import MarketDataResult
from app.services.report.tracking import PerformanceTracker


class StaticMarketData:
    def __init__(self, dataframe):
        self.dataframe = dataframe

    def fetch_price_history(self, *_args, **_kwargs):
        return MarketDataResult(
            dataframe=self.dataframe,
            last_trading_date=self.dataframe.index[-1].to_pydatetime().replace(tzinfo=timezone.utc),
            is_stale=False,
            provider="mock",
            data_quality_note="ok",
            current_price=float(self.dataframe.iloc[-1]["close"]),
        )


class EmptyMarketData:
    def fetch_price_history(self, *_args, **_kwargs):
        return MarketDataResult(pd.DataFrame(), None, True, "mock", "empty", None)


class CapturingMarketData(StaticMarketData):
    def __init__(self, dataframe):
        super().__init__(dataframe)
        self.lookbacks = []

    def fetch_price_history(self, *_args, **kwargs):
        self.lookbacks.append(kwargs["lookback_days"])
        return super().fetch_price_history(*_args, **kwargs)


def price_frame(rows):
    index = pd.to_datetime([row[0] for row in rows])
    return pd.DataFrame(
        {
            "open": [row[1] for row in rows],
            "high": [row[2] for row in rows],
            "low": [row[3] for row in rows],
            "close": [row[4] for row in rows],
            "volume": [1000] * len(rows),
        },
        index=index,
    )


def create_cycle(repository, **overrides):
    data = {
        "report_type": "global",
        "ticker": "AAPL",
        "name": "Apple",
        "action": "BUY",
        "horizon": "medium",
        "status": "active",
        "reference_price": 100,
        "target_price": 110,
        "stop_loss": 90,
        "started_at": "2026-01-01T00:00:00+00:00",
    }
    data.update(overrides)
    return repository.create_recommendation_cycle(data)


def backfill(cycle, dataframe):
    repository = InMemoryRepository()
    stored = create_cycle(repository, **cycle)
    PerformanceTracker(repository, StaticMarketData(dataframe)).backfill_recommendation_cycles()
    return next(row for row in repository.list_recommendation_cycles() if row["id"] == stored["id"])


@pytest.mark.parametrize("action", ["BUY", "HOLD", "WATCH"])
def test_long_actions_use_upside_as_favorable_barrier(action):
    dataframe = price_frame(
        [
            ("2026-01-02", 100, 108, 95, 104),
            ("2026-01-05", 104, 111, 101, 109),
        ]
    )

    updated = backfill({"action": action}, dataframe)

    assert updated["status"] == "hit_target"
    assert updated["barrier_hit_at"] == "2026-01-05T00:00:00+00:00"
    assert updated["closed_at"] == updated["barrier_hit_at"]


@pytest.mark.parametrize("action", ["SELL", "REDUCE"])
def test_short_actions_use_downside_as_favorable_barrier(action):
    dataframe = price_frame(
        [
            ("2026-01-02", 100, 105, 94, 98),
            ("2026-01-05", 98, 101, 89, 91),
        ]
    )

    updated = backfill({"action": action, "target_price": 90, "stop_loss": 110}, dataframe)

    assert updated["status"] == "hit_target"
    assert updated["barrier_hit_at"] == "2026-01-05T00:00:00+00:00"


@pytest.mark.parametrize(
    ("action", "target_price", "stop_loss", "high", "low"),
    [("BUY", 110, 90, 105, 89), ("SELL", 90, 110, 111, 95)],
)
def test_actions_use_directional_adverse_barrier(action, target_price, stop_loss, high, low):
    dataframe = price_frame([("2026-01-02", 100, high, low, 100)])

    updated = backfill(
        {"action": action, "target_price": target_price, "stop_loss": stop_loss}, dataframe
    )

    assert updated["status"] == "hit_stop"
    assert updated["barrier_hit_at"] == "2026-01-02T00:00:00+00:00"


@pytest.mark.parametrize(
    ("action", "target_price", "stop_loss"),
    [("BUY", 110, 90), ("SELL", 90, 110)],
)
def test_same_day_favorable_and_adverse_hits_are_ambiguous(action, target_price, stop_loss):
    dataframe = price_frame([("2026-01-02", 100, 112, 88, 101)])

    updated = backfill(
        {"action": action, "target_price": target_price, "stop_loss": stop_loss}, dataframe
    )

    assert updated["status"] == "ambiguous"
    assert updated["barrier_hit_at"] == "2026-01-02T00:00:00+00:00"
    assert updated["closed_at"] == updated["barrier_hit_at"]


def test_first_barrier_hit_is_chosen_in_trading_date_order():
    dataframe = price_frame(
        [
            ("2026-01-05", 95, 112, 94, 110),
            ("2026-01-02", 100, 105, 89, 92),
        ]
    )

    updated = backfill({}, dataframe)

    assert updated["status"] == "hit_stop"
    assert updated["barrier_hit_at"] == "2026-01-02T00:00:00+00:00"


def test_cycle_still_expires_after_horizon_without_barrier_hit():
    dates = pd.bdate_range("2026-01-02", periods=5)
    dataframe = pd.DataFrame(
        {
            "open": [100] * 5,
            "high": [105] * 5,
            "low": [95] * 5,
            "close": [100] * 5,
            "volume": [1000] * 5,
        },
        index=dates,
    )

    updated = backfill({"horizon": "short"}, dataframe)

    assert updated["status"] == "expired"
    assert updated["closed_at"] == dates[4].to_pydatetime().replace(tzinfo=timezone.utc).isoformat()
    assert updated.get("barrier_hit_at") is None


def test_recalculate_resets_and_rebuilds_existing_terminal_cycles():
    repository = InMemoryRepository()
    cycle = create_cycle(
        repository,
        status="hit_target",
        barrier_hit_at="2026-01-10T00:00:00+00:00",
        closed_at="2026-01-10T00:00:00+00:00",
        price_after_60d=999,
    )
    dataframe = price_frame([("2026-01-02", 100, 105, 89, 92)])
    tracker = PerformanceTracker(repository, StaticMarketData(dataframe))

    recalculated = tracker.recalculate_recommendation_cycles()

    updated = next(
        row for row in repository.list_recommendation_cycles() if row["id"] == cycle["id"]
    )
    assert recalculated == 1
    assert updated["status"] == "hit_stop"
    assert updated["barrier_hit_at"] == "2026-01-02T00:00:00+00:00"
    assert updated["price_after_60d"] is None


def test_recalculate_requests_history_covering_old_cycle_start():
    repository = InMemoryRepository()
    create_cycle(repository, started_at="2020-01-01T00:00:00+00:00")
    market_data = CapturingMarketData(price_frame([("2026-01-02", 100, 105, 89, 92)]))

    PerformanceTracker(repository, market_data).recalculate_recommendation_cycles()

    assert market_data.lookbacks[0] > 365 * 5


def test_recalculate_preserves_existing_cycle_when_history_is_unavailable():
    repository = InMemoryRepository()
    cycle = create_cycle(
        repository,
        status="hit_target",
        barrier_hit_at="2026-01-10T00:00:00+00:00",
        closed_at="2026-01-10T00:00:00+00:00",
    )

    recalculated = PerformanceTracker(
        repository, EmptyMarketData()
    ).recalculate_recommendation_cycles()

    updated = next(
        row for row in repository.list_recommendation_cycles() if row["id"] == cycle["id"]
    )
    assert recalculated == 0
    assert updated["status"] == "hit_target"
    assert updated["barrier_hit_at"] == "2026-01-10T00:00:00+00:00"
