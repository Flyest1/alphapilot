from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from json import dumps
from queue import Queue
from time import perf_counter
import threading
from typing import Any, Mapping, Protocol
from uuid import uuid4

from app.db.supabase_client import Repository
from app.models.advisory import (
    AdvisoryJobRequest,
    AdvisoryJobStatus,
    parse_advisory_job_request,
    validate_advisory_result,
)
from app.utils.datetime import parse_iso_datetime

ACTIVE_JOB_STATUSES = {"queued", "running"}
ACTIVE_JOB_TIMEOUT = timedelta(minutes=20)
ADVISORY_RELATIONS = ("advisory_jobs", "advisory_analyses")
ADVISORY_CAPABILITY_RELATION = "advisory_capabilities"
ADVISORY_HEARTBEAT_INTERVAL_SECONDS = 15.0
ADVISORY_MAX_CONCURRENT_JOBS = 1
UNIQUE_RACE_REQUERY_ATTEMPTS = 3
_job_locks: dict[str, tuple[threading.RLock, int]] = {}
_job_locks_guard = threading.Lock()
_request_hash_locks: dict[str, tuple[threading.Lock, int]] = {}
_request_hash_locks_guard = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request_hash(request: AdvisoryJobRequest) -> str:
    payload = request.model_dump(mode="json", exclude_none=True)
    encoded = dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def is_advisory_migration_required(exc: BaseException) -> bool:
    message = str(exc).casefold()
    code = str(getattr(exc, "code", "") or "").upper()
    if code in {"42P01", "PGRST205"}:
        return any(relation in message for relation in ADVISORY_RELATIONS)
    if is_profit_taking_review_migration_required(exc):
        return True
    if not any(relation in message for relation in ADVISORY_RELATIONS):
        return False
    return (
        "does not exist" in message
        or "could not find the table" in message
        or "could not find table" in message
        or "schema cache" in message
        and "table" in message
    )


def is_profit_taking_review_migration_required(exc: BaseException) -> bool:
    message = str(exc).casefold()
    code = str(getattr(exc, "code", "") or "").upper()
    check_constraint_missing = (
        code == "23514"
        and any(relation in message for relation in ADVISORY_RELATIONS)
        and "analysis_type" in message
    )
    capability_relation_missing = (
        code in {"42P01", "PGRST205"} and ADVISORY_CAPABILITY_RELATION in message
    )
    return check_constraint_missing or capability_relation_missing


def _is_active_request_hash_unique_violation(exc: BaseException) -> bool:
    code = str(getattr(exc, "code", "") or "").upper()
    if code != "23505":
        return False
    parts = [str(exc)]
    for attribute in ("message", "details", "hint"):
        value = getattr(exc, attribute, None)
        if value:
            parts.append(str(value))
    for argument in getattr(exc, "args", ()):
        if isinstance(argument, Mapping):
            parts.extend(
                str(argument.get(key) or "")
                for key in ("message", "details", "hint")
                if argument.get(key)
            )
    message = " ".join(parts).casefold()
    return "advisory_jobs_active_request_hash_idx" in message or (
        "advisory_jobs" in message and "request_hash" in message
    )


@dataclass
class AdvisoryJob:
    job_id: str
    analysis_type: str
    request_payload: dict[str, Any]
    request_hash: str
    status: AdvisoryJobStatus
    created_at: str
    updated_at: str
    analysis_id: str | None = None
    error_code: str | None = None
    message: str | None = None
    step_timings: dict[str, Any] | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "AdvisoryJob":
        return cls(
            job_id=str(row.get("job_id")),
            analysis_type=str(row.get("analysis_type")),
            request_payload=dict(row.get("request_payload") or {}),
            request_hash=str(row.get("request_hash")),
            status=str(row.get("status") or "queued"),
            analysis_id=str(row["analysis_id"]) if row.get("analysis_id") else None,
            error_code=row.get("error_code"),
            message=row.get("message"),
            step_timings=dict(row.get("step_timings") or {}),
            created_at=str(row.get("created_at") or _now_iso()),
            updated_at=str(row.get("updated_at") or _now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("request_payload")
        return data


@dataclass
class AdvisoryAnalysis:
    analysis_id: str
    job_id: str
    analysis_type: str
    request_hash: str
    request: dict[str, Any]
    result: dict[str, Any]
    created_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "AdvisoryAnalysis":
        return cls(
            analysis_id=str(row.get("analysis_id")),
            job_id=str(row.get("job_id")),
            analysis_type=str(row.get("analysis_type")),
            request_hash=str(row.get("request_hash")),
            request=dict(row.get("request_payload") or {}),
            result=dict(row.get("result_payload") or {}),
            created_at=str(row.get("created_at") or _now_iso()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UnsupportedAnalysisError(Exception):
    pass


class AdvisoryAnalysisHandler(Protocol):
    def __call__(self, job: AdvisoryJob, request: AdvisoryJobRequest) -> dict[str, Any]: ...


class AdvisoryAnalysisDispatcher(Protocol):
    def __call__(self, job: AdvisoryJob, request: AdvisoryJobRequest) -> dict[str, Any]: ...


class AdvisoryDispatcher:
    def __init__(self, handlers: Mapping[str, AdvisoryAnalysisHandler] | None = None) -> None:
        self.handlers = dict(handlers or {})

    def __call__(self, job: AdvisoryJob, request: AdvisoryJobRequest) -> dict[str, Any]:
        handler = self.handlers.get(request.analysis_type)
        if handler is None:
            raise UnsupportedAnalysisError(request.analysis_type)
        result = handler(job, request)
        if not isinstance(result, dict):
            raise TypeError("advisory analysis handler must return a dictionary")
        return validate_advisory_result(result)


class AdvisoryJobStore:
    def __init__(
        self,
        repository: Repository,
        active_timeout: timedelta = ACTIVE_JOB_TIMEOUT,
    ) -> None:
        self.repository = repository
        self.active_timeout = active_timeout

    def create_or_get_active(self, request: AdvisoryJobRequest) -> tuple[AdvisoryJob, bool]:
        request_hash = _request_hash(request)
        with _AdvisoryRequestHashLock(request_hash):
            try:
                return self._create_or_get_active_unlocked(request)
            except Exception as exc:
                if not _is_active_request_hash_unique_violation(exc):
                    raise
                for _attempt in range(UNIQUE_RACE_REQUERY_ATTEMPTS):
                    active = self._find_active_request(request_hash)
                    if active is not None:
                        return active, False
                raise

    def _create_or_get_active_unlocked(
        self,
        request: AdvisoryJobRequest,
    ) -> tuple[AdvisoryJob, bool]:
        request_hash = _request_hash(request)
        for row in self.repository.list_advisory_jobs(limit=100):
            if (
                row.get("request_hash") != request_hash
                or row.get("status") not in ACTIVE_JOB_STATUSES
            ):
                continue
            if self._expire_if_stale(row):
                continue
            return AdvisoryJob.from_row(row), False

        payload = request.model_dump(mode="json", exclude_none=True)
        row = self.repository.create_advisory_job(
            {
                "job_id": str(uuid4()),
                "analysis_type": request.analysis_type,
                "request_payload": payload,
                "request_hash": request_hash,
                "status": "queued",
                "step_timings": {},
                "message": "자문 분석 요청을 접수했습니다.",
            }
        )
        return AdvisoryJob.from_row(row), True

    def _find_active_request(self, request_hash: str) -> AdvisoryJob | None:
        for row in self.repository.list_advisory_jobs(limit=100):
            if (
                row.get("request_hash") != request_hash
                or row.get("status") not in ACTIVE_JOB_STATUSES
            ):
                continue
            if self._expire_if_stale(row):
                continue
            return AdvisoryJob.from_row(row)
        return None

    def check_storage(self) -> None:
        """Verify that both advisory persistence relations are queryable."""
        self.repository.list_advisory_jobs(limit=1)
        self.repository.list_advisory_analyses(limit=1)

    def has_capability(self, capability: str) -> bool:
        return self.repository.has_advisory_capability(capability)

    def get(self, job_id: str) -> AdvisoryJob | None:
        row = self.repository.get_advisory_job(job_id)
        if row and self._expire_if_stale(row):
            row = self.repository.get_advisory_job(job_id)
        return AdvisoryJob.from_row(row) if row else None

    def mark_running(self, job_id: str) -> AdvisoryJob | None:
        with _AdvisoryJobLock(job_id):
            return self._mark_running_unlocked(job_id)

    def _mark_running_unlocked(self, job_id: str) -> AdvisoryJob | None:
        row = self.repository.get_advisory_job(job_id)
        if row is None:
            return None
        if row.get("status") not in ACTIVE_JOB_STATUSES:
            return AdvisoryJob.from_row(row)
        return self._update(
            job_id,
            status="running",
            started_at=_now_iso(),
            message="자문 분석을 준비하고 있습니다.",
        )

    def mark_completed(self, job_id: str, analysis_id: str) -> AdvisoryJob | None:
        return self._mark_terminal(
            job_id,
            status="completed",
            analysis_id=analysis_id,
            completed_at=_now_iso(),
            message="자문 분석이 완료되었습니다.",
        )

    def mark_failed(self, job_id: str, error_code: str) -> AdvisoryJob | None:
        return self._mark_terminal(
            job_id,
            status="failed",
            error_code=error_code,
            completed_at=_now_iso(),
            message="자문 분석을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        )

    def create_analysis(self, job: AdvisoryJob, result: dict[str, Any]) -> AdvisoryAnalysis:
        row = self.repository.create_advisory_analysis(
            {
                "analysis_id": str(uuid4()),
                "job_id": job.job_id,
                "analysis_type": job.analysis_type,
                "request_hash": job.request_hash,
                "request_payload": job.request_payload,
                "result_payload": result,
            }
        )
        return AdvisoryAnalysis.from_row(row)

    def mark_step(self, job_id: str, step_name: str, step_status: str, duration_ms: int) -> None:
        row = self.repository.get_advisory_job(job_id)
        if row is None:
            return
        step_timings = dict(row.get("step_timings") or {})
        step_timings[step_name] = {
            "status": step_status,
            "duration_ms": duration_ms,
            "updated_at": _now_iso(),
        }
        self._update(job_id, step_timings=step_timings)

    def heartbeat(self, job_id: str) -> AdvisoryJob | None:
        """Keep active jobs fresh without changing a terminal job state."""
        row = self.repository.get_advisory_job(job_id)
        if row is None or row.get("status") not in ACTIVE_JOB_STATUSES:
            return AdvisoryJob.from_row(row) if row else None
        return self._update(job_id)

    def recover_unfinished_jobs(self) -> list[str]:
        """Reconcile persisted analyses and return active jobs needing one in-process rerun."""
        analyses_by_job = {
            str(row.get("job_id")): row
            for row in self.repository.list_advisory_analyses(limit=None)
            if row.get("job_id") and row.get("analysis_id")
        }
        recovery_job_ids = []
        for row in self.repository.list_advisory_jobs(limit=None):
            if row.get("status") not in ACTIVE_JOB_STATUSES:
                continue
            job_id = str(row.get("job_id") or "")
            analysis = analyses_by_job.get(job_id)
            if analysis:
                self.mark_completed(job_id, str(analysis["analysis_id"]))
            elif job_id:
                recovery_job_ids.append(job_id)
        return recovery_job_ids

    def time_step(self, job_id: str, step_name: str) -> "AdvisoryJobStepTimer":
        return AdvisoryJobStepTimer(self, job_id, step_name)

    def get_analysis(self, analysis_id: str) -> AdvisoryAnalysis | None:
        row = self.repository.get_advisory_analysis(analysis_id)
        return AdvisoryAnalysis.from_row(row) if row else None

    def list_analyses(
        self,
        analysis_type: str | None = None,
        limit: int | None = None,
    ) -> list[AdvisoryAnalysis]:
        return [
            AdvisoryAnalysis.from_row(row)
            for row in self.repository.list_advisory_analyses(
                analysis_type=analysis_type,
                limit=limit,
            )
        ]

    def _expire_if_stale(self, row: Mapping[str, Any]) -> bool:
        if row.get("status") not in ACTIVE_JOB_STATUSES:
            return False
        job_id = str(row.get("job_id") or "")
        if not job_id:
            return False
        with _AdvisoryJobLock(job_id):
            return self._expire_if_stale_unlocked(job_id)

    def _expire_if_stale_unlocked(self, job_id: str) -> bool:
        current = self.repository.get_advisory_job(job_id)
        if current is None or current.get("status") not in ACTIVE_JOB_STATUSES:
            return True
        row = current
        if row.get("status") not in ACTIVE_JOB_STATUSES:
            return False
        timestamp = parse_iso_datetime(row.get("updated_at") or row.get("created_at"))
        if timestamp is None:
            return False
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - timestamp <= self.active_timeout:
            return False
        self.repository.update_advisory_job(
            job_id,
            {
                "status": "failed",
                "error_code": "stale_active_job",
                "completed_at": _now_iso(),
                "message": "응답이 없는 자문 분석 작업을 종료했습니다. 다시 요청할 수 있습니다.",
            },
        )
        return True

    def _mark_terminal(self, job_id: str, **updates: Any) -> AdvisoryJob | None:
        with _AdvisoryJobLock(job_id):
            row = self.repository.get_advisory_job(job_id)
            if row is None:
                return None
            if row.get("status") not in ACTIVE_JOB_STATUSES:
                return AdvisoryJob.from_row(row)
            return self._update(job_id, **updates)

    def _update(self, job_id: str, **updates: Any) -> AdvisoryJob | None:
        updates["updated_at"] = _now_iso()
        row = self.repository.update_advisory_job(job_id, updates)
        return AdvisoryJob.from_row(row) if row else None


class AdvisoryJobStepTimer:
    def __init__(self, store: AdvisoryJobStore, job_id: str, step_name: str) -> None:
        self.store = store
        self.job_id = job_id
        self.step_name = step_name
        self.started_at = 0.0

    def __enter__(self) -> "AdvisoryJobStepTimer":
        self.started_at = perf_counter()
        return self

    def __exit__(self, exc_type: object, _exc: object, _traceback: object) -> None:
        duration_ms = int((perf_counter() - self.started_at) * 1000)
        step_status = "failed" if exc_type else "completed"
        self.store.mark_step(self.job_id, self.step_name, step_status, duration_ms)


class AdvisoryJobHeartbeat:
    def __init__(
        self,
        store: AdvisoryJobStore,
        job_id: str,
        interval_seconds: float = ADVISORY_HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self.store = store
        self.job_id = job_id
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=max(1.0, self.interval_seconds + 1.0))

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval_seconds):
            self.store.heartbeat(self.job_id)


class _AdvisoryJobLock:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.lock: threading.RLock | None = None

    def __enter__(self) -> "_AdvisoryJobLock":
        with _job_locks_guard:
            lock, references = _job_locks.get(self.job_id, (threading.RLock(), 0))
            _job_locks[self.job_id] = (lock, references + 1)
            self.lock = lock
        self.lock.acquire()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        if self.lock is None:
            return
        self.lock.release()
        with _job_locks_guard:
            current_lock, references = _job_locks[self.job_id]
            if current_lock is self.lock and references == 1:
                _job_locks.pop(self.job_id, None)
            elif current_lock is self.lock:
                _job_locks[self.job_id] = (self.lock, references - 1)


class _AdvisoryRequestHashLock:
    def __init__(self, request_hash: str) -> None:
        self.request_hash = request_hash
        self.lock: threading.Lock | None = None

    def __enter__(self) -> "_AdvisoryRequestHashLock":
        with _request_hash_locks_guard:
            lock, references = _request_hash_locks.get(
                self.request_hash,
                (threading.Lock(), 0),
            )
            _request_hash_locks[self.request_hash] = (lock, references + 1)
            self.lock = lock
        self.lock.acquire()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        if self.lock is None:
            return
        self.lock.release()
        with _request_hash_locks_guard:
            current_lock, references = _request_hash_locks[self.request_hash]
            if current_lock is self.lock and references == 1:
                _request_hash_locks.pop(self.request_hash, None)
            elif current_lock is self.lock:
                _request_hash_locks[self.request_hash] = (self.lock, references - 1)


class AdvisoryJobRunner:
    """Bounded in-process advisory runner that keeps API request threads responsive."""

    def __init__(
        self,
        store: AdvisoryJobStore,
        dispatcher: AdvisoryAnalysisDispatcher,
        max_workers: int = ADVISORY_MAX_CONCURRENT_JOBS,
    ) -> None:
        if max_workers < 1:
            raise ValueError("advisory runner max_workers must be positive")
        self.store = store
        self.dispatcher = dispatcher
        self.max_workers = max_workers
        self._queue: Queue[str | None] = Queue()
        self._lock = threading.Lock()
        self._scheduled: set[str] = set()
        self._active: set[str] = set()
        self._shutdown = False
        self._threads = [
            threading.Thread(
                target=self._worker,
                name=f"advisory-runner-{index + 1}",
                daemon=True,
            )
            for index in range(max_workers)
        ]
        for thread in self._threads:
            thread.start()

    def submit(self, job_id: str) -> bool:
        with self._lock:
            if self._shutdown or job_id in self._scheduled:
                return False
            self._scheduled.add(job_id)
        self._queue.put(job_id)
        return True

    def status(self) -> dict[str, int]:
        with self._lock:
            active_count = len(self._active)
            return {
                "active_count": active_count,
                "queued_count": max(0, len(self._scheduled) - active_count),
                "max_workers": self.max_workers,
            }

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
        for _thread in self._threads:
            self._queue.put(None)

    def _worker(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id is None:
                self._queue.task_done()
                return
            with self._lock:
                self._active.add(job_id)
            try:
                run_advisory_job(self.store, self.dispatcher, job_id)
            except Exception:
                try:
                    self.store.mark_failed(job_id, "internal_error")
                except Exception:
                    pass
            finally:
                with self._lock:
                    self._active.discard(job_id)
                    self._scheduled.discard(job_id)
                self._queue.task_done()


def run_advisory_job(
    store: AdvisoryJobStore,
    dispatcher: AdvisoryAnalysisDispatcher,
    job_id: str,
    heartbeat_interval_seconds: float = ADVISORY_HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    with _AdvisoryJobLock(job_id):
        job = store.mark_running(job_id)
        if job is None or job.status not in ACTIVE_JOB_STATUSES:
            return
        heartbeat = AdvisoryJobHeartbeat(store, job_id, heartbeat_interval_seconds)
        heartbeat.start()
        try:
            with store.time_step(job_id, "analysis"):
                request = parse_advisory_job_request(job.request_payload)
                result = dispatcher(job, request)
                analysis = store.create_analysis(job, result)
        except UnsupportedAnalysisError:
            heartbeat.stop()
            store.mark_failed(job_id, "unsupported_analysis")
        except Exception:
            heartbeat.stop()
            store.mark_failed(job_id, "internal_error")
        else:
            heartbeat.stop()
            store.mark_completed(job_id, analysis.analysis_id)
