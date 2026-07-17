from time import sleep

from fastapi.testclient import TestClient

from app.db.supabase_client import InMemoryRepository
from app.main import create_app
from app.models.advisory import parse_advisory_job_request
from app.services.advisory.job_service import AdvisoryDispatcher, AdvisoryJobStore


def test_startup_recovers_queued_advisory_job_once():
    repository = InMemoryRepository()
    store = AdvisoryJobStore(repository)
    job, _created = store.create_or_get_active(
        parse_advisory_job_request({"analysis_type": "ai_beneficiaries"})
    )
    calls = []

    def handler(_job, request):
        calls.append(request.analysis_type)
        return {
            "analysis_type": request.analysis_type,
            "rows": [],
            "verified_ai_beneficiaries": [],
            "ai_theme_caution": [],
            "evidence": [],
            "data_quality": {"status": "partial"},
            "disclaimer": "investment decision-support information",
        }

    app = create_app(repository=repository)
    app.state.advisory_dispatcher = AdvisoryDispatcher({"ai_beneficiaries": handler})
    with TestClient(app):
        for _ in range(50):
            recovered = store.get(job.job_id)
            if recovered and recovered.status == "completed":
                break
            sleep(0.01)

    completed = store.get(job.job_id)
    assert completed is not None
    assert completed.status == "completed"
    assert calls == ["ai_beneficiaries"]
