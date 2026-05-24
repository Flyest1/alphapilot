from fastapi.testclient import TestClient

from app.db.supabase_client import InMemoryRepository
from app.main import create_app

AUTH = {"Authorization": "Bearer test-api-token"}


def test_performance_logs_endpoint_returns_strategy_context():
    repo = InMemoryRepository()
    strategy = repo.create_strategy(
        {
            "report_id": "report-1",
            "ticker": "AAPL",
            "name": "Apple",
            "action": "HOLD",
            "confidence": 62,
            "current_price": 100,
            "reasoning": "risk-managed hold",
            "risk": "market volatility",
            "invalidation_condition": "close below support",
        }
    )
    repo.create_performance_log(
        {
            "strategy_id": strategy["id"],
            "ticker": "AAPL",
            "action": "HOLD",
            "price_at_recommendation": 100,
            "price_after_1d": 102,
            "return_after_1d": 2,
        }
    )
    test_client = TestClient(create_app(repository=repo))

    response = test_client.get("/api/performance-logs", headers=AUTH)

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["ticker"] == "AAPL"
    assert rows[0]["report_id"] == "report-1"
    assert rows[0]["name"] == "Apple"
    assert rows[0]["confidence"] == 62
    assert rows[0]["return_after_1d"] == 2
