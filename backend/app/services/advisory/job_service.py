from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from json import dumps
from time import perf_counter
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
    if not any(relation in message for relation in ADVISORY_RELATIONS):
        return False
    return (
        "does not exist" in message
        or "could not find the table" in message
        or "could not find table" in message
        or "schema cache" in message
        and "table" in message
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

    def check_storage(self) -> None:
        """Verify that both advisory persistence relations are queryable."""
        self.repository.list_advisory_jobs(limit=1)
        self.repository.list_advisory_analyses(limit=1)

    def get(self, job_id: str) -> AdvisoryJob | None:
        row = self.repository.get_advisory_job(job_id)
        if row and self._expire_if_stale(row):
            row = self.repository.get_advisory_job(job_id)
        return AdvisoryJob.from_row(row) if row else None

    def mark_running(self, job_id: str) -> AdvisoryJob | None:
        return self._update(
            job_id,
            status="running",
            started_at=_now_iso(),
            message="자문 분석을 준비하고 있습니다.",
        )

    def mark_completed(self, job_id: str, analysis_id: str) -> AdvisoryJob | None:
        return self._update(
            job_id,
            status="completed",
            analysis_id=analysis_id,
            completed_at=_now_iso(),
            message="자문 분석이 완료되었습니다.",
        )

    def mark_failed(self, job_id: str, error_code: str) -> AdvisoryJob | None:
        return self._update(
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
        timestamp = parse_iso_datetime(row.get("updated_at") or row.get("created_at"))
        if timestamp is None:
            return False
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - timestamp <= self.active_timeout:
            return False
        self.repository.update_advisory_job(
            str(row.get("job_id")),
            {
                "status": "failed",
                "error_code": "stale_active_job",
                "completed_at": _now_iso(),
                "message": "응답이 없는 자문 분석 작업을 종료했습니다. 다시 요청할 수 있습니다.",
            },
        )
        return True

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


def run_advisory_job(
    store: AdvisoryJobStore,
    dispatcher: AdvisoryAnalysisDispatcher,
    job_id: str,
) -> None:
    job = store.mark_running(job_id)
    if job is None:
        return
    try:
        with store.time_step(job_id, "analysis"):
            request = parse_advisory_job_request(job.request_payload)
            result = dispatcher(job, request)
            analysis = store.create_analysis(job, result)
        store.mark_completed(job_id, analysis.analysis_id)
    except UnsupportedAnalysisError:
        store.mark_failed(job_id, "unsupported_analysis")
    except Exception:
        store.mark_failed(job_id, "internal_error")
