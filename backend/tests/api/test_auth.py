from fastapi.testclient import TestClient

from app.db.supabase_client import InMemoryRepository
from app.main import create_app


def client():
    return TestClient(create_app(repository=InMemoryRepository()))


def test_api_endpoints_reject_missing_and_invalid_api_token():
    test_client = client()

    assert test_client.get("/api/assets").status_code == 401
    response = test_client.get("/api/assets", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_api_endpoint_accepts_valid_api_token():
    test_client = client()

    response = test_client.get(
        "/api/assets",
        headers={"Authorization": "Bearer test-api-token"},
    )

    assert response.status_code == 200
    assert response.json() == []


def test_scheduler_endpoint_rejects_wrong_token():
    test_client = client()

    response = test_client.post(
        "/api/reports/domestic/generate",
        headers={"Authorization": "Bearer test-api-token"},
    )

    assert response.status_code == 401
