from fastapi.testclient import TestClient

from app.db.supabase_client import InMemoryRepository
from app.main import create_app
from app.services.report_service import ReportService
from app.services.toss_invest_service import TossInvestService

AUTH = {"Authorization": "Bearer test-api-token"}


def seed_champion(repository: InMemoryRepository) -> dict:
    champion = repository.create_signal_model_version(
        {
            "model_key": "technical_score",
            "version": "v1",
            "config": {"weights": {"trend": 30}},
        }
    )
    repository.create_signal_model_assignment(
        {"model_version_id": champion["id"], "role": "champion"}
    )
    return champion


class MissingSignalModelMigrationRepository(InMemoryRepository):
    def list_signal_model_versions(self):
        raise RuntimeError(
            "Could not find the table 'public.signal_model_versions' in the schema cache"
        )


class PermissionDeniedSignalModelRepository(InMemoryRepository):
    def list_signal_model_versions(self):
        raise RuntimeError("permission denied for table signal_model_versions")


def test_signal_model_evaluation_requires_normal_api_token():
    client = TestClient(create_app(repository=InMemoryRepository()))

    response = client.get("/api/signal-models/evaluation")

    assert response.status_code == 401


def test_signal_model_evaluation_has_no_mutation_route():
    client = TestClient(create_app(repository=InMemoryRepository()))

    response = client.post("/api/signal-models/evaluation", headers=AUTH)

    assert response.status_code == 405


def test_signal_model_evaluation_returns_final_not_configured_contract():
    repository = InMemoryRepository()
    champion = seed_champion(repository)
    client = TestClient(create_app(repository=repository))

    response = client.get("/api/signal-models/evaluation", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "schema_version",
        "availability",
        "state",
        "research_only",
        "adoption_permitted",
        "evaluation_window_weeks",
        "champion",
        "challenger",
        "active_evaluation",
        "samples",
        "thresholds",
        "promotion",
    }
    assert body["schema_version"] == "signal-model-evaluation-v1"
    assert body["availability"] == "available"
    assert body["state"] == "not_configured"
    assert body["research_only"] is True
    assert body["adoption_permitted"] is False
    assert body["evaluation_window_weeks"] == 12
    assert body["champion"]["id"] == champion["id"]
    assert body["challenger"] is None
    assert body["active_evaluation"] is None
    assert body["samples"] == {"official_scheduled": 0, "manual_input_links": 0}
    assert body["thresholds"] == {"state": "unconfigured", "values": None}
    assert body["promotion"] == {"automatic": False, "eligible": None}


def test_signal_model_evaluation_reports_migration_required_without_zero_samples():
    client = TestClient(create_app(repository=MissingSignalModelMigrationRepository()))

    response = client.get("/api/signal-models/evaluation", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["availability"] == "migration_required"
    assert body["state"] == "unavailable"
    assert body["samples"] == {"official_scheduled": None, "manual_input_links": None}


def test_signal_model_evaluation_returns_503_for_permission_or_generic_storage_failure():
    client = TestClient(create_app(repository=PermissionDeniedSignalModelRepository()))

    response = client.get("/api/signal-models/evaluation", headers=AUTH)

    assert response.status_code == 503
    assert response.json() == {"detail": "signal model evaluation storage is unavailable"}


def test_report_routes_pass_scheduled_or_manual_generation_source(monkeypatch):
    captured_sources = []

    def fake_generate_report(_self, _report_type, generation_source="manual"):
        captured_sources.append(generation_source)
        return {"id": "report-id"}

    monkeypatch.setattr(TossInvestService, "sync_holdings", lambda _self: None)
    monkeypatch.setattr(ReportService, "generate_report", fake_generate_report)
    client = TestClient(create_app(repository=InMemoryRepository()))

    scheduled = client.post(
        "/api/reports/domestic/generate",
        headers={"Authorization": "Bearer test-scheduler-token"},
    )
    manual = client.post("/api/reports/domestic/manual-generate", headers=AUTH)

    assert scheduled.status_code == 202
    assert manual.status_code == 202
    assert captured_sources == ["scheduled", "manual"]
