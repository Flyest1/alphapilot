from app.db.supabase_client import InMemoryRepository


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


def test_market_data_cache_roundtrip():
    repo = InMemoryRepository()
    repo.upsert_market_data_cache("KR:005930:180:2:2026-06-11", {"frame": "{}"})

    row = repo.get_market_data_cache("KR:005930:180:2:2026-06-11")

    assert row["payload"] == {"frame": "{}"}
    assert repo.get_market_data_cache("missing") is None
