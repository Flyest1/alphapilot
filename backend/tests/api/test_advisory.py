from fastapi.testclient import TestClient

import app.main as main_module
from app.db.supabase_client import InMemoryRepository
from app.main import create_app
from app.services.advisory.job_service import AdvisoryDispatcher

AUTH = {"Authorization": "Bearer test-api-token"}


def test_create_app_injects_configured_sec_and_fred_providers(monkeypatch):
    configured = main_module.get_environment_settings().model_copy(
        update={
            "fred_api_key": "test-fred-key",
            "sec_edgar_user_agent": "AlphaPilot test contact@example.com",
        }
    )
    monkeypatch.setattr(main_module, "get_environment_settings", lambda: configured)

    app = main_module.create_app(repository=InMemoryRepository())

    assert app.state.advisory_sec_edgar_configured is True
    assert app.state.advisory_fred_configured is True


class MissingAdvisoryMigrationRepository(InMemoryRepository):
    @staticmethod
    def _missing_relation():
        exc = RuntimeError(
            "Could not find the table 'public.advisory_analyses' in the schema cache"
        )
        exc.code = "PGRST205"
        raise exc

    def list_advisory_analyses(self, analysis_type=None, limit=None):
        self._missing_relation()

    def list_advisory_jobs(self, limit=None):
        self._missing_relation()


class MissingAdvisoryJobsMigrationRepository(InMemoryRepository):
    def list_advisory_jobs(self, limit=None):
        exc = RuntimeError("Could not find the table 'public.advisory_jobs' in the schema cache")
        exc.code = "PGRST205"
        raise exc


def test_advisory_routes_require_normal_api_token():
    client = TestClient(create_app(repository=InMemoryRepository()))

    response = client.post("/api/advisory/jobs", json={"analysis_type": "sector_outlook"})

    assert response.status_code == 401


def test_advisory_status_reports_storage_and_ai_configuration():
    client = TestClient(create_app(repository=InMemoryRepository()))

    response = client.get("/api/advisory/status", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {
        "storage_status": "available",
        "ai_narrative_status": "not_configured",
        "migration_file": "backend/app/db/migrations/017_create_advisory_analyses.sql",
    }


def test_advisory_status_requires_advisory_jobs_relation_too():
    client = TestClient(create_app(repository=MissingAdvisoryJobsMigrationRepository()))

    response = client.get("/api/advisory/status", headers=AUTH)

    assert response.status_code == 200
    assert response.json()["storage_status"] == "migration_required"


def test_advisory_routes_report_required_migration_without_generic_500():
    client = TestClient(create_app(repository=MissingAdvisoryMigrationRepository()))

    status_response = client.get("/api/advisory/status", headers=AUTH)
    list_response = client.get("/api/advisory/analyses", headers=AUTH)
    create_response = client.post(
        "/api/advisory/jobs",
        headers=AUTH,
        json={"analysis_type": "sector_outlook"},
    )

    assert status_response.status_code == 200
    assert status_response.json()["storage_status"] == "migration_required"
    for response in (list_response, create_response):
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "migration_required"


def test_advisory_job_rejects_unknown_request_fields():
    client = TestClient(create_app(repository=InMemoryRepository()))

    response = client.post(
        "/api/advisory/jobs",
        headers=AUTH,
        json={"analysis_type": "sector_outlook", "unknown": "not allowed"},
    )

    assert response.status_code == 422


def test_advisory_job_returns_202_and_safe_failure_when_handler_is_unregistered():
    app = create_app(repository=InMemoryRepository())
    app.state.advisory_dispatcher = AdvisoryDispatcher()
    client = TestClient(app)

    response = client.post(
        "/api/advisory/jobs",
        headers=AUTH,
        json={"analysis_type": "sector_outlook"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    job = client.get(f"/api/advisory/jobs/{body['job_id']}", headers=AUTH)
    assert job.status_code == 200
    assert job.json()["status"] == "failed"
    assert job.json()["error_code"] == "unsupported_analysis"
    assert job.json()["step_timings"]["analysis"]["status"] == "failed"


def test_advisory_job_persists_and_lists_registered_handler_output():
    app = create_app(repository=InMemoryRepository())

    def handler(_job, request):
        return {
            "analysis_type": request.analysis_type,
            "etfs": [{"ticker": "SCHD"}],
            "caution_etfs": [],
            "relatively_stable_etfs": [],
            "beginner_explanation": "분배금과 총수익률을 함께 확인합니다.",
            "evidence": [],
            "data_quality": {"status": "partial"},
            "disclaimer": "투자 의사결정 지원 정보입니다.",
        }

    app.state.advisory_dispatcher = AdvisoryDispatcher({"high_dividend_etfs": handler})
    client = TestClient(app)

    response = client.post(
        "/api/advisory/jobs",
        headers=AUTH,
        json={"analysis_type": "high_dividend_etfs", "max_results": 3},
    )

    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "queued"
    completed_job = client.get(f"/api/advisory/jobs/{job['job_id']}", headers=AUTH).json()
    assert completed_job["status"] == "completed"
    assert completed_job["analysis_id"]
    assert completed_job["step_timings"]["analysis"]["status"] == "completed"
    analysis = client.get(f"/api/advisory/analyses/{completed_job['analysis_id']}", headers=AUTH)
    assert analysis.status_code == 200
    assert analysis.json()["result"]["analysis_type"] == "high_dividend_etfs"
    assert analysis.json()["result"]["etfs"] == [{"ticker": "SCHD"}]
    listed = client.get("/api/advisory/analyses?analysis_type=high_dividend_etfs", headers=AUTH)
    assert listed.status_code == 200
    assert [row["analysis_id"] for row in listed.json()] == [completed_job["analysis_id"]]
