from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from app.db.supabase_client import Repository

ACTIVE_JOB_STATUSES = {"queued", "running"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ReportGenerationJob:
    job_id: str
    report_type: str
    status: str
    created_at: str
    updated_at: str
    report_id: str | None = None
    message: str | None = None
    error_category: str | None = None
    step_timings: dict | None = None

    @classmethod
    def from_row(cls, row: dict) -> "ReportGenerationJob":
        return cls(
            job_id=str(row.get("job_id")),
            report_type=str(row.get("report_type")),
            status=str(row.get("status") or "queued"),
            report_id=row.get("report_id"),
            message=row.get("message"),
            error_category=row.get("error_category"),
            step_timings=row.get("step_timings") or {},
            created_at=str(row.get("created_at") or _now_iso()),
            updated_at=str(row.get("updated_at") or _now_iso()),
        )

    def to_dict(self) -> dict:
        return asdict(self)


class ReportJobStore:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def create_or_get_active(self, report_type: str) -> tuple[ReportGenerationJob, bool]:
        for row in self.repository.list_report_jobs(limit=20):
            if row.get("report_type") == report_type and row.get("status") in ACTIVE_JOB_STATUSES:
                return ReportGenerationJob.from_row(row), False

        row = self.repository.create_report_job(
            {
                "job_id": str(uuid4()),
                "report_type": report_type,
                "status": "queued",
                "message": "리포트 생성 요청을 접수했습니다.",
                "step_timings": {},
            }
        )
        return ReportGenerationJob.from_row(row), True

    def get(self, job_id: str) -> ReportGenerationJob | None:
        row = self.repository.get_report_job(job_id)
        return ReportGenerationJob.from_row(row) if row else None

    def mark_running(self, job_id: str) -> ReportGenerationJob | None:
        return self._update(
            job_id,
            status="running",
            message="리포트를 생성하는 중입니다.",
        )

    def mark_completed(
        self,
        job_id: str,
        report_id: str | None,
        step_timings: dict | None = None,
    ) -> ReportGenerationJob | None:
        return self._update(
            job_id,
            status="completed",
            report_id=report_id,
            step_timings=step_timings,
            message="리포트 생성이 완료되었습니다.",
        )

    def mark_failed(
        self,
        job_id: str,
        error_category: str = "internal_error",
        step_timings: dict | None = None,
    ) -> ReportGenerationJob | None:
        return self._update(
            job_id,
            status="failed",
            error_category=error_category,
            step_timings=step_timings,
            message="리포트 생성에 실패했습니다. 잠시 후 다시 시도하세요.",
        )

    def mark_step(self, job_id: str, step_name: str, status: str, duration_ms: int) -> None:
        row = self.repository.get_report_job(job_id)
        if not row:
            return
        step_timings = dict(row.get("step_timings") or {})
        step_timings[step_name] = {
            "status": status,
            "duration_ms": duration_ms,
            "updated_at": _now_iso(),
        }
        self.repository.update_report_job(job_id, {"step_timings": step_timings})

    def time_step(self, job_id: str, step_name: str) -> "ReportJobStepTimer":
        return ReportJobStepTimer(self, job_id, step_name)

    def _update(self, job_id: str, **updates: str | None | dict) -> ReportGenerationJob | None:
        row = self.repository.update_report_job(job_id, updates)
        return ReportGenerationJob.from_row(row) if row else None


class ReportJobStepTimer:
    def __init__(self, store: ReportJobStore, job_id: str, step_name: str) -> None:
        self.store = store
        self.job_id = job_id
        self.step_name = step_name
        self.started_at = 0.0

    def __enter__(self) -> "ReportJobStepTimer":
        self.started_at = perf_counter()
        return self

    def __exit__(self, exc_type: object, _exc: object, _traceback: object) -> None:
        duration_ms = int((perf_counter() - self.started_at) * 1000)
        status = "failed" if exc_type else "completed"
        self.store.mark_step(self.job_id, self.step_name, status, duration_ms)
