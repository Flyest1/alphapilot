from fastapi.testclient import TestClient

from app.db.supabase_client import InMemoryRepository
from app.main import create_app
from app.services.toss_invest_service import TossInvestService

AUTH = {"Authorization": "Bearer test-api-token"}


def test_toss_status_is_user_token_protected():
    client = TestClient(create_app(repository=InMemoryRepository()))

    assert client.get("/api/toss/status").status_code == 401
    response = client.get("/api/toss/status", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert "client-secret" not in response.text
    assert "client-id" not in response.text


def test_toss_sync_returns_400_when_credentials_missing():
    client = TestClient(create_app(repository=InMemoryRepository()))

    response = client.post("/api/toss/sync", headers=AUTH)

    assert response.status_code == 400
    assert "credentials are not configured" in response.json()["detail"]


def test_toss_sync_endpoint_returns_service_result(monkeypatch):
    monkeypatch.setenv("TOSS_INVEST_CLIENT_ID", "client-id")
    monkeypatch.setenv("TOSS_INVEST_CLIENT_SECRET", "client-secret")

    def fake_sync(_self):
        return {
            "provider": "toss_invest",
            "mode": "read_only",
            "account": {"account_seq": "1"},
            "synced_at": "2026-06-18T00:00:00+00:00",
            "synced_count": 1,
            "created_count": 1,
            "updated_count": 0,
            "stale_count": 0,
            "duplicate_manual_assets": [],
            "overview": {},
        }

    monkeypatch.setattr(TossInvestService, "sync_holdings", fake_sync)
    client = TestClient(create_app(repository=InMemoryRepository()))

    response = client.post("/api/toss/sync", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["synced_count"] == 1
