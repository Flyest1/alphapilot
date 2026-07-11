from fastapi.testclient import TestClient

from app.db.supabase_client import InMemoryRepository
from app.main import create_app

AUTH = {"Authorization": "Bearer test-api-token"}


def test_recommendation_stats_endpoint_returns_grouped_stats():
    repo = InMemoryRepository()
    repo.create_recommendation_cycle(
        {
            "report_type": "domestic",
            "ticker": "005930",
            "name": "Samsung",
            "action": "BUY",
            "horizon": "medium",
            "status": "hit_target",
            "reference_price": 100,
            "return_after_20d": 8.5,
            "technical_score": 72,
            "base_confidence": 72,
            "calibrated_confidence": 72,
            "metadata": {},
            "started_at": "2026-01-01T00:00:00+00:00",
            "closed_at": "2026-01-10T00:00:00+00:00",
        }
    )
    test_client = TestClient(create_app(repository=repo))

    response = test_client.get("/api/recommendation-stats", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["totals"]["closed_count"] == 1
    assert body["totals"]["win_rate"] == 1.0
    group = body["groups"][0]
    assert group["action"] == "BUY"
    assert group["score_band"] == "70s"
    assert group["avg_return_20d"] == 8.5
    assert group["calibration_applied"] is False


def test_recommendation_stats_requires_token():
    test_client = TestClient(create_app(repository=InMemoryRepository()))

    response = test_client.get("/api/recommendation-stats")

    assert response.status_code == 401
