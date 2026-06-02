from app.db.supabase_client import InMemoryRepository
from app.services.report_job_service import ReportJobStore


def test_report_job_store_reuses_active_job_for_same_report_type():
    store = ReportJobStore(InMemoryRepository())

    first, first_created = store.create_or_get_active("domestic")
    second, second_created = store.create_or_get_active("domestic")

    assert first_created is True
    assert second_created is False
    assert second.job_id == first.job_id


def test_report_job_store_allows_new_job_after_completion():
    store = ReportJobStore(InMemoryRepository())
    first, _created = store.create_or_get_active("global")

    store.mark_running(first.job_id)
    completed = store.mark_completed(first.job_id, "report-1")
    second, second_created = store.create_or_get_active("global")

    assert completed is not None
    assert completed.status == "completed"
    assert completed.report_id == "report-1"
    assert second_created is True
    assert second.job_id != first.job_id


def test_report_job_store_marks_failure_without_exposing_raw_error():
    store = ReportJobStore(InMemoryRepository())
    job, _created = store.create_or_get_active("domestic")

    failed = store.mark_failed(job.job_id)

    assert failed is not None
    assert failed.status == "failed"
    assert "실패" in (failed.message or "")


def test_report_job_store_records_step_timings():
    store = ReportJobStore(InMemoryRepository())
    job, _created = store.create_or_get_active("domestic")

    store.mark_step(job.job_id, "market_data", "completed", 120)
    updated = store.get(job.job_id)

    assert updated is not None
    assert updated.step_timings["market_data"]["duration_ms"] == 120


def test_report_job_store_expires_stale_active_job_and_allows_new_job():
    repo = InMemoryRepository()
    stale = repo.create_report_job(
        {
            "report_type": "domestic",
            "status": "running",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )
    store = ReportJobStore(repo)

    second, created = store.create_or_get_active("domestic")
    expired = store.get(stale["job_id"])

    assert created is True
    assert second.job_id != stale["job_id"]
    assert expired is not None
    assert expired.status == "failed"
    assert expired.error_category == "stale_active_job"
