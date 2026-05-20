from fastapi.testclient import TestClient

from app.db.supabase_client import InMemoryRepository
from app.main import create_app

AUTH = {"Authorization": "Bearer test-api-token"}


def test_asset_crud_endpoints():
    test_client = TestClient(create_app(repository=InMemoryRepository()))
    payload = {
        "market": "US",
        "ticker": "AAPL",
        "name": "Apple",
        "quantity": 3,
        "avg_price": 100,
        "currency": "USD",
        "memo": "core holding",
    }

    created = test_client.post("/api/assets", headers=AUTH, json=payload)
    assert created.status_code == 201
    asset = created.json()
    assert asset["ticker"] == "AAPL"

    listed = test_client.get("/api/assets", headers=AUTH)
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    updated = test_client.put(
        f"/api/assets/{asset['id']}",
        headers=AUTH,
        json={"quantity": 4},
    )
    assert updated.status_code == 200
    assert updated.json()["quantity"] == 4

    deleted = test_client.delete(f"/api/assets/{asset['id']}", headers=AUTH)
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
