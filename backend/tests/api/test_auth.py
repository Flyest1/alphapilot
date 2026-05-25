from fastapi.testclient import TestClient

from app.db.supabase_client import InMemoryRepository
from app.main import create_app
from app.services.report_service import ReportService


def client():
    return TestClient(create_app(repository=InMemoryRepository()))


def test_root_endpoint_reports_backend_status():
    response = client().get("/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "alphapilot-backend",
        "status": "ok",
        "health": "/health",
    }


def test_api_endpoints_reject_missing_and_invalid_api_token():
    test_client = client()

    assert test_client.get("/api/assets").status_code == 401
    response = test_client.get(
        "/api/assets",
        headers={
            "Authorization": "Bearer wrong",
            "Origin": "http://localhost:5173",
        },
    )
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


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


def test_manual_report_endpoint_uses_api_token(monkeypatch):
    monkeypatch.setattr(
        ReportService,
        "generate_report",
        lambda _self, report_type: {"report_type": report_type, "status": "generated"},
    )
    test_client = client()

    response = test_client.post(
        "/api/reports/domestic/manual-generate",
        headers={"Authorization": "Bearer test-api-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"report_type": "domestic", "status": "generated"}
