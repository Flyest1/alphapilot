from app.services.report_job_service import ReportJobStore


def test_report_job_store_reuses_active_job_for_same_report_type():
    store = ReportJobStore()

    first, first_created = store.create_or_get_active("domestic")
    second, second_created = store.create_or_get_active("domestic")

    assert first_created is True
    assert second_created is False
    assert second.job_id == first.job_id


def test_report_job_store_allows_new_job_after_completion():
    store = ReportJobStore()
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
    store = ReportJobStore()
    job, _created = store.create_or_get_active("domestic")

    failed = store.mark_failed(job.job_id)

    assert failed is not None
    assert failed.status == "failed"
    assert "실패" in (failed.message or "")
