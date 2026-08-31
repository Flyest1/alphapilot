from fastapi.testclient import TestClient

from app.config import clear_settings_cache
from app.db.supabase_client import InMemoryRepository
from app.main import create_app
from app.services.report_service import ReportService
from app.services.toss_invest_service import TossInvestService


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


def test_cors_accepts_comma_separated_frontend_origins(monkeypatch):
    monkeypatch.setenv(
        "FRONTEND_ORIGIN",
        "http://localhost:5173,http://127.0.0.1:5175",
    )
    clear_settings_cache()
    test_client = client()

    response = test_client.options(
        "/api/settings",
        headers={
            "Origin": "http://127.0.0.1:5175",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5175"


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


def test_scheduler_report_endpoint_queues_job_with_scheduler_token(monkeypatch):
    execution_order = []
    monkeypatch.setattr(
        TossInvestService,
        "sync_holdings",
        lambda _self: execution_order.append("toss_sync"),
    )
    monkeypatch.setattr(
        ReportService,
        "generate_report",
        lambda _self, report_type, generation_source="manual": (
            execution_order.append("report_generation")
            or {
                "id": "report-1",
                "report_type": report_type,
            }
        ),
    )
    test_client = client()

    response = test_client.post(
        "/api/reports/global/generate",
        headers={"Authorization": "Bearer test-scheduler-token"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["report_type"] == "global"
    assert body["status"] == "queued"

    status_response = test_client.get(
        f"/api/reports/manual-jobs/{body['job_id']}",
        headers={"Authorization": "Bearer test-api-token"},
    )

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"
    assert execution_order == ["toss_sync", "report_generation"]


def test_scheduler_report_stops_when_toss_sync_fails(monkeypatch):
    report_generated = False

    def fail_sync(_self):
        raise RuntimeError("asset persistence failed")

    def generate_report(_self, report_type, generation_source="manual"):
        nonlocal report_generated
        report_generated = True
        return {"id": "unexpected", "report_type": report_type}

    monkeypatch.setattr(TossInvestService, "sync_holdings", fail_sync)
    monkeypatch.setattr(ReportService, "generate_report", generate_report)
    test_client = client()

    response = test_client.post(
        "/api/reports/domestic/generate",
        headers={"Authorization": "Bearer test-scheduler-token"},
    )
    body = response.json()
    status_response = test_client.get(
        f"/api/reports/manual-jobs/{body['job_id']}",
        headers={"Authorization": "Bearer test-api-token"},
    )

    assert response.status_code == 202
    assert status_response.json()["status"] == "failed"
    assert status_response.json()["error_category"] == "toss_sync_error"
    assert status_response.json()["step_timings"]["toss_sync"]["status"] == "failed"
    assert report_generated is False


def test_manual_report_endpoint_uses_api_token(monkeypatch):
    toss_sync_called = False

    def sync_holdings(_self):
        nonlocal toss_sync_called
        toss_sync_called = True

    monkeypatch.setattr(TossInvestService, "sync_holdings", sync_holdings)
    monkeypatch.setattr(
        ReportService,
        "generate_report",
        lambda _self, report_type, generation_source="manual": {
            "id": "report-1",
            "report_type": report_type,
        },
    )
    test_client = client()

    response = test_client.post(
        "/api/reports/domestic/manual-generate",
        headers={"Authorization": "Bearer test-api-token"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["report_type"] == "domestic"
    assert body["status"] == "queued"

    status_response = test_client.get(
        f"/api/reports/manual-jobs/{body['job_id']}",
        headers={"Authorization": "Bearer test-api-token"},
    )

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "completed"
    assert toss_sync_called is False


def test_manual_report_job_status_returns_404_for_unknown_job():
    test_client = client()

    response = test_client.get(
        "/api/reports/manual-jobs/missing",
        headers={"Authorization": "Bearer test-api-token"},
    )

    assert response.status_code == 404
