from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event, Lock
from time import sleep

import pytest
from pydantic import ValidationError

from app.db.supabase_client import InMemoryRepository
from app.models.advisory import parse_advisory_job_request, validate_advisory_result
from app.services.advisory import job_service
from app.services.advisory.job_service import (
    AdvisoryDispatcher,
    AdvisoryJobRunner,
    AdvisoryJobStore,
    run_advisory_job,
)


class TrackingAdvisoryRepository(InMemoryRepository):
    def __init__(self):
        super().__init__()
        self.storage_checks = []

    def list_advisory_jobs(self, limit=None):
        self.storage_checks.append(("advisory_jobs", limit))
        return super().list_advisory_jobs(limit)

    def list_advisory_analyses(self, analysis_type=None, limit=None):
        self.storage_checks.append(("advisory_analyses", limit))
        return super().list_advisory_analyses(analysis_type, limit)


class HeartbeatTrackingRepository(InMemoryRepository):
    def __init__(self):
        super().__init__()
        self.updates = []

    def update_advisory_job(self, job_id, data):
        self.updates.append(dict(data))
        return super().update_advisory_job(job_id, data)


class ConcurrentCreateRepository(InMemoryRepository):
    def __init__(self):
        super().__init__()
        self.create_calls = 0
        self.create_lock = Lock()

    def create_advisory_job(self, data):
        with self.create_lock:
            self.create_calls += 1
        return super().create_advisory_job(data)


class AdvisoryUniqueViolation(RuntimeError):
    def __init__(self, constraint, details):
        super().__init__(f'duplicate key violates unique constraint "{constraint}"')
        self.code = "23505"
        self.details = details


class UniqueRaceRepository(InMemoryRepository):
    def __init__(self):
        super().__init__()
        self.create_calls = 0
        self.winner_job_id = None

    def create_advisory_job(self, data):
        self.create_calls += 1
        winner = super().create_advisory_job(data)
        self.winner_job_id = winner["job_id"]
        raise AdvisoryUniqueViolation(
            "advisory_jobs_active_request_hash_idx",
            f"Key (request_hash)=({data['request_hash']}) already exists.",
        )


class InvisibleUniqueRaceRepository(InMemoryRepository):
    def __init__(self):
        super().__init__()
        self.list_calls = 0
        self.error = AdvisoryUniqueViolation(
            "advisory_jobs_active_request_hash_idx",
            "Key (request_hash)=(hidden) already exists.",
        )

    def list_advisory_jobs(self, limit=None):
        self.list_calls += 1
        return []

    def create_advisory_job(self, data):
        raise self.error


class UnrelatedUniqueErrorRepository(InMemoryRepository):
    def __init__(self):
        super().__init__()
        self.error = AdvisoryUniqueViolation(
            "unrelated_table_external_id_key",
            "Key (external_id)=(duplicate) already exists.",
        )

    def create_advisory_job(self, data):
        raise self.error


def ai_beneficiaries_result(request):
    return {
        "analysis_type": request.analysis_type,
        "rows": [],
        "verified_ai_beneficiaries": [],
        "ai_theme_caution": [],
        "evidence": [],
        "data_quality": {"status": "partial"},
        "disclaimer": "investment decision-support information",
    }


def test_all_supported_advisory_request_types_validate_strictly():
    payloads = [
        {"analysis_type": "undervalued_us_stocks"},
        {"analysis_type": "etf_rebalancing", "positions": [{"ticker": "VT"}]},
        {"analysis_type": "post_earnings_opportunities"},
        {"analysis_type": "ai_beneficiaries"},
        {"analysis_type": "high_dividend_etfs"},
        {"analysis_type": "sec_filing_risk", "ticker": "AAPL"},
        {"analysis_type": "etf_overlap", "positions": [{"ticker": "VOO", "weight_pct": 60}]},
        {"analysis_type": "sector_outlook", "custom_proxies": {"technology": "XLK"}},
        {"analysis_type": "profit_taking_review", "asset_id": "asset-1"},
        {"analysis_type": "high_upside_speculative_stocks", "tickers": ["BIOX"]},
    ]

    for payload in payloads:
        request = parse_advisory_job_request(payload)
        assert request.analysis_type == payload["analysis_type"]

    with pytest.raises(ValidationError):
        parse_advisory_job_request(
            {"analysis_type": "ai_beneficiaries", "unexpected_parameter": True}
        )

    with pytest.raises(ValidationError):
        parse_advisory_job_request({"analysis_type": "sec_filing_risk", "tickers": ["AAPL"]})

    with pytest.raises(ValidationError):
        parse_advisory_job_request({"analysis_type": "etf_overlap", "positions": []})

    with pytest.raises(ValidationError):
        parse_advisory_job_request({"analysis_type": "profit_taking_review"})


def test_advisory_result_contract_rejects_missing_required_feature_fields():
    with pytest.raises(ValidationError):
        validate_advisory_result(
            {
                "analysis_type": "sector_outlook",
                "evidence": [],
                "data_quality": {},
                "disclaimer": "투자 의사결정 지원 정보입니다.",
            }
        )


def test_advisory_job_store_reuses_active_request_hash():
    store = AdvisoryJobStore(InMemoryRepository())
    request = parse_advisory_job_request(
        {"analysis_type": "undervalued_us_stocks", "max_results": 5}
    )

    first, first_created = store.create_or_get_active(request)
    second, second_created = store.create_or_get_active(request)

    assert first_created is True
    assert second_created is False
    assert second.job_id == first.job_id
    assert second.request_hash == first.request_hash


def test_request_hash_lock_serializes_concurrent_in_memory_creation():
    repository = ConcurrentCreateRepository()
    stores = [AdvisoryJobStore(repository), AdvisoryJobStore(repository)]
    request = parse_advisory_job_request(
        {"analysis_type": "undervalued_us_stocks", "max_results": 5}
    )
    barrier = Barrier(2)

    def create(store):
        barrier.wait()
        return store.create_or_get_active(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create, stores))

    assert repository.create_calls == 1
    assert {job.job_id for job, _created in results} == {results[0][0].job_id}
    assert sorted(created for _job, created in results) == [False, True]


def test_unique_request_hash_race_requeries_active_winner():
    repository = UniqueRaceRepository()
    store = AdvisoryJobStore(repository)
    request = parse_advisory_job_request({"analysis_type": "sector_outlook"})

    job, created = store.create_or_get_active(request)

    assert created is False
    assert repository.create_calls == 1
    assert job.job_id == repository.winner_job_id
    assert job.status == "queued"


def test_unique_request_hash_race_requery_is_bounded_and_reraises_original():
    repository = InvisibleUniqueRaceRepository()
    store = AdvisoryJobStore(repository)
    request = parse_advisory_job_request({"analysis_type": "sector_outlook"})

    with pytest.raises(AdvisoryUniqueViolation) as raised:
        store.create_or_get_active(request)

    assert raised.value is repository.error
    assert repository.list_calls == 4


def test_unrelated_unique_database_error_is_not_hidden():
    repository = UnrelatedUniqueErrorRepository()
    store = AdvisoryJobStore(repository)
    request = parse_advisory_job_request({"analysis_type": "sector_outlook"})

    with pytest.raises(AdvisoryUniqueViolation) as raised:
        store.create_or_get_active(request)

    assert raised.value is repository.error


def test_advisory_storage_check_minimally_queries_both_relations():
    repository = TrackingAdvisoryRepository()

    AdvisoryJobStore(repository).check_storage()

    assert repository.storage_checks == [("advisory_jobs", 1), ("advisory_analyses", 1)]


def test_advisory_job_store_expires_stale_active_request_before_recreating():
    repository = InMemoryRepository()
    request = parse_advisory_job_request({"analysis_type": "sector_outlook"})
    stale = repository.create_advisory_job(
        {
            "analysis_type": request.analysis_type,
            "request_payload": request.model_dump(mode="json"),
            "request_hash": "a" * 64,
            "status": "running",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )
    store = AdvisoryJobStore(repository, active_timeout=timedelta(minutes=20))

    created, was_created = store.create_or_get_active(request)
    expired = store.get(stale["job_id"])

    assert was_created is True
    assert created.job_id != stale["job_id"]
    assert expired is not None
    assert expired.status == "failed"
    assert expired.error_code == "stale_active_job"


def test_unregistered_analysis_fails_with_safe_unsupported_code():
    store = AdvisoryJobStore(InMemoryRepository())
    job, _created = store.create_or_get_active(
        parse_advisory_job_request(
            {"analysis_type": "etf_overlap", "positions": [{"ticker": "VT"}]}
        )
    )

    run_advisory_job(store, AdvisoryDispatcher(), job.job_id)

    failed = store.get(job.job_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_code == "unsupported_analysis"
    assert failed.step_timings["analysis"]["status"] == "failed"
    assert "etf_overlap" not in (failed.message or "")


def test_registered_dispatcher_persists_completed_analysis():
    store = AdvisoryJobStore(InMemoryRepository())
    job, _created = store.create_or_get_active(
        parse_advisory_job_request({"analysis_type": "ai_beneficiaries", "themes": ["chips"]})
    )

    def handler(_job, request):
        return {
            "analysis_type": request.analysis_type,
            "rows": [],
            "verified_ai_beneficiaries": [],
            "ai_theme_caution": [],
            "evidence": [],
            "data_quality": {"status": "partial"},
            "disclaimer": "투자 의사결정 지원 정보입니다.",
        }

    run_advisory_job(store, AdvisoryDispatcher({"ai_beneficiaries": handler}), job.job_id)

    completed = store.get(job.job_id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.analysis_id is not None
    assert completed.step_timings["analysis"]["status"] == "completed"
    analysis = store.get_analysis(completed.analysis_id)
    assert analysis is not None
    assert analysis.result["analysis_type"] == "ai_beneficiaries"
    assert analysis.result["verified_ai_beneficiaries"] == []


def test_failed_terminal_state_ignores_late_completed_transition():
    store = AdvisoryJobStore(InMemoryRepository())
    job, _created = store.create_or_get_active(
        parse_advisory_job_request({"analysis_type": "sector_outlook"})
    )

    failed = store.mark_failed(job.job_id, "internal_error")
    late_completed = store.mark_completed(job.job_id, "late-analysis")

    assert failed is not None
    assert late_completed is not None
    assert late_completed.status == "failed"
    assert late_completed.error_code == "internal_error"
    assert late_completed.analysis_id is None


def test_completed_terminal_state_ignores_late_failed_transition():
    store = AdvisoryJobStore(InMemoryRepository())
    job, _created = store.create_or_get_active(
        parse_advisory_job_request({"analysis_type": "sector_outlook"})
    )

    completed = store.mark_completed(job.job_id, "analysis-1")
    late_failed = store.mark_failed(job.job_id, "late_error")

    assert completed is not None
    assert late_failed is not None
    assert late_failed.status == "completed"
    assert late_failed.analysis_id == "analysis-1"
    assert late_failed.error_code is None


def test_running_job_heartbeat_updates_timestamp_without_reverting_terminal_state():
    repository = HeartbeatTrackingRepository()
    store = AdvisoryJobStore(repository)
    job, _created = store.create_or_get_active(
        parse_advisory_job_request({"analysis_type": "ai_beneficiaries"})
    )

    def handler(_job, request):
        sleep(0.04)
        return ai_beneficiaries_result(request)

    run_advisory_job(
        store,
        AdvisoryDispatcher({"ai_beneficiaries": handler}),
        job.job_id,
        heartbeat_interval_seconds=0.01,
    )

    completed = store.get(job.job_id)
    assert completed is not None
    assert completed.status == "completed"
    assert any(set(update) == {"updated_at"} for update in repository.updates)
    assert store.heartbeat(job.job_id).status == "completed"


def test_recovery_reconciles_saved_analysis_and_returns_only_missing_jobs():
    repository = InMemoryRepository()
    store = AdvisoryJobStore(repository)
    reconciled, _created = store.create_or_get_active(
        parse_advisory_job_request({"analysis_type": "ai_beneficiaries"})
    )
    repository.update_advisory_job(reconciled.job_id, {"status": "running"})
    store.create_analysis(
        reconciled,
        ai_beneficiaries_result(parse_advisory_job_request({"analysis_type": "ai_beneficiaries"})),
    )
    pending, _created = store.create_or_get_active(
        parse_advisory_job_request({"analysis_type": "sector_outlook"})
    )

    recovery_job_ids = store.recover_unfinished_jobs()

    repaired = store.get(reconciled.job_id)
    assert repaired is not None
    assert repaired.status == "completed"
    assert repaired.analysis_id is not None
    assert recovery_job_ids == [pending.job_id]


def test_in_process_job_lock_makes_duplicate_recovery_execution_idempotent():
    repository = InMemoryRepository()
    store = AdvisoryJobStore(repository)
    job, _created = store.create_or_get_active(
        parse_advisory_job_request({"analysis_type": "ai_beneficiaries"})
    )
    calls = []

    def handler(_job, request):
        calls.append(request.analysis_type)
        sleep(0.04)
        return ai_beneficiaries_result(request)

    dispatcher = AdvisoryDispatcher({"ai_beneficiaries": handler})
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(run_advisory_job, store, dispatcher, job.job_id) for _ in range(2)
        ]
        for future in futures:
            future.result()

    completed = store.get(job.job_id)
    assert calls == ["ai_beneficiaries"]
    assert completed is not None
    assert completed.status == "completed"
    assert len(store.list_analyses()) == 1


def test_advisory_runner_bounds_concurrency_and_reports_queue_depth():
    store = AdvisoryJobStore(InMemoryRepository())
    jobs = [
        store.create_or_get_active(
            parse_advisory_job_request({"analysis_type": "ai_beneficiaries", "themes": [theme]})
        )[0]
        for theme in ("chips", "software")
    ]
    first_started = Event()
    release_first = Event()
    calls = []

    def handler(_job, request):
        calls.append(request.themes[0])
        if request.themes[0] == "chips":
            first_started.set()
            release_first.wait(timeout=1)
        return ai_beneficiaries_result(request)

    runner = AdvisoryJobRunner(
        store,
        AdvisoryDispatcher({"ai_beneficiaries": handler}),
        max_workers=1,
    )
    try:
        assert runner.submit(jobs[0].job_id) is True
        assert runner.submit(jobs[0].job_id) is False
        assert first_started.wait(timeout=1)
        assert runner.submit(jobs[1].job_id) is True
        assert runner.status() == {
            "active_count": 1,
            "queued_count": 1,
            "max_workers": 1,
        }
        release_first.set()
        for _ in range(100):
            if all(store.get(job.job_id).status == "completed" for job in jobs):
                break
            sleep(0.01)
    finally:
        release_first.set()
        runner.shutdown()

    assert calls == ["chips", "software"]
    assert runner.status()["active_count"] == 0
    assert runner.status()["queued_count"] == 0


def test_advisory_runner_continues_after_unhandled_job_failure(monkeypatch):
    store = AdvisoryJobStore(InMemoryRepository())
    jobs = [
        store.create_or_get_active(
            parse_advisory_job_request({"analysis_type": "ai_beneficiaries", "themes": [theme]})
        )[0]
        for theme in ("first", "second")
    ]
    original_run = job_service.run_advisory_job
    calls = []

    def flaky_run(current_store, dispatcher, job_id):
        calls.append(job_id)
        if job_id == jobs[0].job_id:
            raise RuntimeError("unexpected runner failure")
        original_run(current_store, dispatcher, job_id)

    monkeypatch.setattr(job_service, "run_advisory_job", flaky_run)
    runner = AdvisoryJobRunner(
        store,
        AdvisoryDispatcher(
            {
                "ai_beneficiaries": lambda _job, request: ai_beneficiaries_result(request),
            }
        ),
    )
    try:
        assert runner.submit(jobs[0].job_id)
        assert runner.submit(jobs[1].job_id)
        for _ in range(100):
            if all(store.get(job.job_id).status in {"completed", "failed"} for job in jobs):
                break
            sleep(0.01)
    finally:
        runner.shutdown()

    assert calls == [jobs[0].job_id, jobs[1].job_id]
    assert store.get(jobs[0].job_id).status == "failed"
    assert store.get(jobs[1].job_id).status == "completed"
