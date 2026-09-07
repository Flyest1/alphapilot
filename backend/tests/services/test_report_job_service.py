from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace

from app.api.reports import _run_report_job
from app.db.supabase_client import InMemoryRepository
from app.services.notification_service import NotificationService
from app.services.report_job_service import ReportJobStore
from app.services.report_service import ReportService
from app.services.toss_invest_service import TossInvestService


def test_report_job_store_reuses_active_job_for_same_report_type():
    store = ReportJobStore(InMemoryRepository())

    first, first_created = store.create_or_get_active("domestic")
    second, second_created = store.create_or_get_active("domestic")

    assert first_created is True
    assert second_created is False
    assert second.job_id == first.job_id


def test_report_jobs_of_same_type_are_serialized_across_generation_sources(monkeypatch):
    repository = InMemoryRepository()
    store = ReportJobStore(repository)
    manual_job, _created = store.create_or_get_active("domestic", "manual")
    scheduled_job, _created = store.create_or_get_active("domestic", "scheduled")
    first_entered = Event()
    release_first = Event()
    second_entered = Event()
    state_lock = Lock()
    active_count = 0
    max_active_count = 0

    def generate_report(_self, report_type, generation_source="manual"):
        nonlocal active_count, max_active_count
        with state_lock:
            active_count += 1
            max_active_count = max(max_active_count, active_count)
        try:
            if generation_source == "manual":
                first_entered.set()
                assert release_first.wait(timeout=2)
            else:
                second_entered.set()
            return {"id": f"{generation_source}-report", "report_type": report_type}
        finally:
            with state_lock:
                active_count -= 1

    monkeypatch.setattr(
        TossInvestService,
        "status",
        lambda _self: {
            "configured": False,
            "client_id_configured": False,
            "client_secret_configured": False,
            "account_id_configured": False,
            "provider": "toss_invest",
            "mode": "read_only",
        },
    )
    monkeypatch.setattr(ReportService, "generate_report", generate_report)
    monkeypatch.setattr(
        NotificationService,
        "create_scheduled_report_notifications",
        lambda _self, _report, _previous_cycle_states: [],
    )
    app_state = SimpleNamespace(report_jobs=store, market_data_service=object())

    with ThreadPoolExecutor(max_workers=2) as executor:
        manual_future = executor.submit(
            _run_report_job,
            app_state,
            repository,
            "domestic",
            manual_job.job_id,
            False,
        )
        assert first_entered.wait(timeout=2)
        scheduled_future = executor.submit(
            _run_report_job,
            app_state,
            repository,
            "domestic",
            scheduled_job.job_id,
            True,
        )
        try:
            assert not second_entered.wait(timeout=0.2)
        finally:
            release_first.set()
        manual_future.result(timeout=2)
        scheduled_future.result(timeout=2)

    assert second_entered.is_set()
    assert max_active_count == 1


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
