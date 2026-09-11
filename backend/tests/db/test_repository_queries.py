import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pandas as pd
import pytest
from httpx import RemoteProtocolError
from tenacity import wait_none

from app.db.supabase_client import InMemoryRepository, SupabaseRepository
from app.services.report.tracking import PerformanceTracker


class _RetryBuilder:
    def __init__(self) -> None:
        self.attempts = 0

    def execute(self) -> str:
        self.attempts += 1
        if self.attempts < 3:
            raise RemoteProtocolError("Server disconnected")
        return "ok"


class _ConcurrentTracker:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0


class _ConcurrentBuilder:
    def __init__(self, tracker: _ConcurrentTracker) -> None:
        self.tracker = tracker

    def execute(self) -> str:
        with self.tracker.lock:
            self.tracker.active += 1
            self.tracker.max_active = max(self.tracker.max_active, self.tracker.active)
        time.sleep(0.02)
        with self.tracker.lock:
            self.tracker.active -= 1
        return "ok"


class _CaptureResponse:
    def __init__(self, data):
        self.data = data


class _CaptureUpdateBuilder:
    def __init__(self):
        self.payload = None

    def update(self, payload):
        self.payload = payload
        return self

    def eq(self, *_args):
        return self

    def execute(self):
        return _CaptureResponse([{"id": "cycle-1", **self.payload}])


class _CaptureClient:
    def __init__(self):
        self.builder = _CaptureUpdateBuilder()

    def table(self, _name):
        return self.builder


class _CaptureRpcBuilder:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return _CaptureResponse(self.data)


class _CaptureRpcClient:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def rpc(self, function_name, params):
        self.calls.append((function_name, params))
        return _CaptureRpcBuilder(self.data)


def test_supabase_repository_retries_httpx_transport_errors(monkeypatch):
    repository = SupabaseRepository(client=object())
    builder = _RetryBuilder()
    monkeypatch.setattr(SupabaseRepository._execute.retry, "wait", wait_none())

    assert repository._execute(builder) == "ok"
    assert builder.attempts == 3


def test_supabase_repository_serializes_shared_client_requests():
    repository = SupabaseRepository(client=object())
    tracker = _ConcurrentTracker()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                repository._execute,
                [_ConcurrentBuilder(tracker), _ConcurrentBuilder(tracker)],
            )
        )

    assert results == ["ok", "ok"]
    assert tracker.max_active == 1


def test_recommendation_cycle_update_preserves_explicit_nulls():
    client = _CaptureClient()
    repository = SupabaseRepository(client=client)

    repository.update_recommendation_cycle(
        "cycle-1",
        {"status": "active", "closed_at": None, "barrier_hit_at": None},
    )

    assert client.builder.payload == {
        "status": "active",
        "closed_at": None,
        "barrier_hit_at": None,
    }

    memory_repository = InMemoryRepository()
    cycle = memory_repository.create_recommendation_cycle(
        {"ticker": "AAPL", "status": "hit_target", "closed_at": "2026-01-01"}
    )
    updated = memory_repository.update_recommendation_cycle(
        cycle["id"], {"status": "active", "closed_at": None}
    )

    assert updated["closed_at"] is None


def test_supabase_toss_reconciliation_uses_one_atomic_rpc():
    result = {
        "assets": [{"id": "asset-1", "external_asset_key": "US:AAPL"}],
        "created_count": 1,
        "updated_count": 0,
        "stale_count": 2,
    }
    client = _CaptureRpcClient(result)
    repository = SupabaseRepository(client=client)
    asset_rows = [
        {
            "market": "US",
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "quantity": 10,
            "avg_price": 155.3,
            "currency": "USD",
            "memo": "Toss Invest Open API read-only sync",
            "external_asset_key": "US:AAPL",
            "external_payload": {"symbol": "AAPL"},
        }
    ]

    reconciled = repository.reconcile_toss_assets("1", "2026-09-07T00:00:00+00:00", asset_rows)

    assert reconciled == result
    assert client.calls == [
        (
            "reconcile_toss_holdings",
            {
                "p_account_id": "1",
                "p_synced_at": "2026-09-07T00:00:00+00:00",
                "p_assets": asset_rows,
            },
        )
    ]


def test_list_unevaluated_performance_logs_excludes_completed_rows():
    repo = InMemoryRepository()
    open_log = repo.create_performance_log({"ticker": "AAPL", "action": "BUY"})
    repo.create_performance_log({"ticker": "MSFT", "action": "BUY", "price_after_20d": 120})

    rows = repo.list_unevaluated_performance_logs(limit=10)

    assert [row["id"] for row in rows] == [open_log["id"]]


def test_list_open_recommendation_cycles_keeps_active_and_unevaluated():
    repo = InMemoryRepository()
    active = repo.create_recommendation_cycle({"ticker": "A", "status": "active"})
    pending = repo.create_recommendation_cycle({"ticker": "B", "status": "hit_target"})
    repo.create_recommendation_cycle({"ticker": "C", "status": "expired", "price_after_60d": 100})

    rows = repo.list_open_recommendation_cycles(limit=10)

    assert {row["id"] for row in rows} == {active["id"], pending["id"]}


class _CappedQuery:
    def __init__(self, rows):
        self.rows = rows
        self.orders = []
        self.bounds = (0, 99999)

    def select(self, _columns):
        return self

    def is_(self, field, _value):
        self.rows = [row for row in self.rows if row.get(field) is None]
        return self

    def or_(self, _expression):
        self.rows = [
            row
            for row in self.rows
            if row.get("status") == "active" or row.get("price_after_60d") is None
        ]
        return self

    def order(self, field, desc=False):
        self.orders.append((field, desc))
        return self

    def limit(self, count):
        self.bounds = (0, count - 1)
        return self

    def range(self, start, end):
        self.bounds = (start, end)
        return self

    def execute(self):
        rows = self.rows
        for field, desc in reversed(self.orders):
            rows = sorted(rows, key=lambda row: row[field], reverse=desc)
        start, end = self.bounds
        return _CaptureResponse(rows[start : min(end + 1, start + 73)])


class _CappedClient:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return _CappedQuery(self.rows)


@pytest.mark.parametrize(
    "method",
    ["list_open_recommendation_cycles", "list_unevaluated_performance_logs", "list_strategies"],
)
def test_pending_queries_paginate_past_server_cap_with_stable_tie_order(method):
    rows = [{"id": f"{i:04d}", "created_at": "2020-01-01", "status": "active"} for i in range(1101)]
    repo = SupabaseRepository(client=_CappedClient(rows))
    result = getattr(repo, method)()
    assert [row["id"] for row in result] == [f"{i:04d}" for i in reversed(range(1101))]


@pytest.mark.parametrize(
    "method", ["list_open_recommendation_cycles", "list_unevaluated_performance_logs"]
)
def test_pending_queries_preserve_explicit_limit_across_server_pages(method):
    rows = [{"id": f"{i:04d}", "created_at": "2020-01-01", "status": "active"} for i in range(600)]
    result = getattr(SupabaseRepository(client=_CappedClient(rows)), method)(limit=250)
    assert len(result) == 250
    assert result[-1]["id"] == "0350"


def test_cycle_backfill_gathers_pages_before_pending_updates_shrink_results(monkeypatch):
    rows = [
        {
            "id": f"{i:04d}",
            "created_at": "2020-01-01",
            "started_at": "2020-01-01",
            "status": "active",
            "ticker": "AAPL",
            "reference_price": 100,
        }
        for i in range(1101)
    ]
    repo = SupabaseRepository(client=_CappedClient(rows))
    frame = pd.DataFrame({"close": [100] * 81}, index=pd.bdate_range("2020-01-01", periods=81))
    market = SimpleNamespace(fetch_price_history=lambda *a, **kw: SimpleNamespace(dataframe=frame))

    def persist(cycle_id, updates):
        next(row for row in rows if row["id"] == cycle_id).update(updates)

    monkeypatch.setattr(repo, "update_recommendation_cycle", persist)
    PerformanceTracker(repo, market).backfill_recommendation_cycles()
    assert len([row for row in rows if row.get("price_after_60d") == 100]) == 1101
    assert all(row["status"] == "expired" for row in rows)


def test_market_data_cache_roundtrip():
    repo = InMemoryRepository()
    repo.upsert_market_data_cache("KR:005930:180:2:2026-06-11", {"frame": "{}"})

    row = repo.get_market_data_cache("KR:005930:180:2:2026-06-11")

    assert row["payload"] == {"frame": "{}"}
    assert repo.get_market_data_cache("missing") is None


def test_candidate_universe_upsert_and_report_type_filter():
    repo = InMemoryRepository()
    repo.upsert_candidate_universe(
        {
            "report_type": "domestic",
            "market": "KR",
            "ticker": "005930",
            "name": "삼성전자",
            "source": "seed",
            "source_rank": 2,
        }
    )
    repo.upsert_candidate_universe(
        {
            "report_type": "global",
            "market": "ETF",
            "ticker": "QQQ",
            "name": "QQQ",
            "source": "seed",
            "source_rank": 1,
        }
    )

    assert [row["ticker"] for row in repo.list_candidate_universe("domestic")] == ["005930"]
    assert {row["ticker"] for row in repo.list_candidate_universe()} == {"005930", "QQQ"}


def test_notification_repository_read_state_and_dedup_lookup():
    repo = InMemoryRepository()
    row = repo.create_notification(
        {
            "event_key": "report_completed:1",
            "event_type": "report_completed",
            "title": "완료",
            "message": "완료",
        }
    )

    assert repo.get_notification_by_event_key("report_completed:1")["id"] == row["id"]
    assert len(repo.list_notifications(unread_only=True)) == 1
    assert repo.mark_all_notifications_read() == 1
    assert repo.list_notifications(unread_only=True) == []
