from fastapi.testclient import TestClient

from app.db.supabase_client import InMemoryRepository
from app.main import create_app


def test_candidate_asset_crud_endpoints():
    repository = InMemoryRepository()
    test_client = TestClient(create_app(repository=repository))
    headers = {"Authorization": "Bearer test-api-token"}

    create_response = test_client.post(
        "/api/candidates",
        headers=headers,
        json={
            "market": "US",
            "ticker": "QQQ",
            "name": "Invesco QQQ Trust",
            "currency": "USD",
            "memo": "growth ETF",
            "is_active": True,
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["ticker"] == "QQQ"
    assert created["is_active"] is True

    update_response = test_client.put(
        f"/api/candidates/{created['id']}",
        headers=headers,
        json={"is_active": False, "memo": "paused"},
    )

    assert update_response.status_code == 200
    assert update_response.json()["is_active"] is False
    assert update_response.json()["memo"] == "paused"

    list_response = test_client.get("/api/candidates", headers=headers)

    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    delete_response = test_client.delete(f"/api/candidates/{created['id']}", headers=headers)

    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True}
    assert repository.list_candidate_assets() == []
