from fastapi.testclient import TestClient

from app.db.supabase_client import InMemoryRepository
from app.main import create_app


def test_recommendation_cycles_endpoint_lists_cycles():
    repository = InMemoryRepository()
    repository.create_recommendation_cycle(
        {
            "report_type": "domestic",
            "ticker": "005930",
            "name": "Samsung",
            "action": "BUY",
            "horizon": "medium",
            "status": "active",
            "reference_price": 100,
        }
    )
    test_client = TestClient(create_app(repository=repository))

    response = test_client.get(
        "/api/recommendation-cycles",
        headers={"Authorization": "Bearer test-api-token"},
    )

    assert response.status_code == 200
    assert response.json()[0]["ticker"] == "005930"
