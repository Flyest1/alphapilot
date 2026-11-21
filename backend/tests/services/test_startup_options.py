from copy import deepcopy
from time import sleep

from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from app.config import clear_settings_cache, get_environment_settings
from app.db.supabase_client import InMemoryRepository
from app.main import create_app
from app.models.advisory import parse_advisory_job_request
from app.services.advisory.job_service import AdvisoryDispatcher, AdvisoryJobStore

AUTH = {"Authorization": "Bearer test-api-token"}


@pytest.mark.parametrize("legacy_model", ["gpt-5.4-mini", "gpt-5.6-luna"])
def test_disabled_startup_model_upgrade_preserves_stored_settings(monkeypatch, legacy_model):
    monkeypatch.setenv("STARTUP_UPGRADE_LEGACY_AI_MODEL", "false")
    repository = InMemoryRepository()
    repository.upsert_settings({"ai_model": legacy_model, "risk_profile": "aggressive"})
    original = deepcopy(repository.get_settings())

    app = create_app(repository=repository)

    assert repository.get_settings() == original
    assert app.state.application_settings.ai_model == legacy_model
    with TestClient(app) as client:
        response = client.post("/api/settings", headers=AUTH, json={"ai_model": "gpt-6-luna"})
    assert response.status_code == 200
    assert repository.get_settings()["ai_model"] == "gpt-6-luna"


def test_disabled_recovery_leaves_existing_jobs_untouched_and_accepts_manual_jobs(monkeypatch):
    monkeypatch.setenv("STARTUP_RECOVER_ADVISORY_JOBS", "false")
    repository = InMemoryRepository()
    store = AdvisoryJobStore(repository)
    pending, _ = store.create_or_get_active(
        parse_advisory_job_request({"analysis_type": "ai_beneficiaries", "tickers": ["AAPL"]})
    )
    saved, _ = store.create_or_get_active(
        parse_advisory_job_request({"analysis_type": "ai_beneficiaries", "tickers": ["GOOG"]})
    )
    store.mark_running(saved.job_id)
    result = {
        "analysis_type": "ai_beneficiaries",
        "rows": [],
        "verified_ai_beneficiaries": [],
        "ai_theme_caution": [],
        "evidence": [],
        "data_quality": {"status": "partial"},
        "disclaimer": "investment decision-support information",
    }
    store.create_analysis(saved, result)
    original_jobs = deepcopy(repository.list_advisory_jobs())
    original_analyses = deepcopy(repository.list_advisory_analyses())

    app = create_app(repository=repository)
    app.state.advisory_dispatcher = AdvisoryDispatcher({"ai_beneficiaries": lambda *_: result})
    with TestClient(app) as client:
        assert repository.list_advisory_jobs() == original_jobs
        assert repository.list_advisory_analyses() == original_analyses
        assert app.state.advisory_runner.status()["active_count"] == 0
        assert app.state.advisory_runner.status()["queued_count"] == 0
        response = client.post(
            "/api/advisory/jobs",
            headers=AUTH,
            json={"analysis_type": "ai_beneficiaries", "tickers": ["MSFT"]},
        )
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        for _ in range(100):
            if repository.get_advisory_job(job_id)["status"] == "completed":
                break
            sleep(0.01)
        assert repository.get_advisory_job(job_id)["status"] == "completed"
        assert repository.get_advisory_job(pending.job_id)["status"] == "queued"
        assert repository.get_advisory_job(saved.job_id)["status"] == "running"
    assert len(repository.list_advisory_analyses()) == len(original_analyses) + 1


@pytest.mark.parametrize(
    "name", ["STARTUP_UPGRADE_LEGACY_AI_MODEL", "STARTUP_RECOVER_ADVISORY_JOBS"]
)
def test_invalid_startup_flag_rejects_configuration(monkeypatch, name):
    monkeypatch.setenv(name, "flase")
    clear_settings_cache()
    with pytest.raises(ValidationError):
        get_environment_settings()
