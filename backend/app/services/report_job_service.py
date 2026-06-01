from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

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

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


class ReportJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, ReportGenerationJob] = {}
        self._lock = Lock()

    def create_or_get_active(self, report_type: str) -> tuple[ReportGenerationJob, bool]:
        with self._lock:
            for job in reversed(list(self._jobs.values())):
                if job.report_type == report_type and job.status in ACTIVE_JOB_STATUSES:
                    return job, False

            now = _now_iso()
            job = ReportGenerationJob(
                job_id=str(uuid4()),
                report_type=report_type,
                status="queued",
                created_at=now,
                updated_at=now,
                message="리포트 생성 요청을 접수했습니다.",
            )
            self._jobs[job.job_id] = job
            self._prune_locked()
            return job, True

    def get(self, job_id: str) -> ReportGenerationJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def mark_running(self, job_id: str) -> ReportGenerationJob | None:
        return self._update(
            job_id,
            status="running",
            message="리포트를 생성하는 중입니다.",
        )

    def mark_completed(self, job_id: str, report_id: str | None) -> ReportGenerationJob | None:
        return self._update(
            job_id,
            status="completed",
            report_id=report_id,
            message="리포트 생성이 완료되었습니다.",
        )

    def mark_failed(self, job_id: str) -> ReportGenerationJob | None:
        return self._update(
            job_id,
            status="failed",
            message="리포트 생성에 실패했습니다. 잠시 후 다시 시도하세요.",
        )

    def _update(self, job_id: str, **updates: str | None) -> ReportGenerationJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for key, value in updates.items():
                setattr(job, key, value)
            job.updated_at = _now_iso()
            return job

    def _prune_locked(self) -> None:
        max_jobs = 50
        if len(self._jobs) <= max_jobs:
            return
        removable = [
            job_id for job_id, job in self._jobs.items() if job.status not in ACTIVE_JOB_STATUSES
        ]
        for job_id in removable[: len(self._jobs) - max_jobs]:
            self._jobs.pop(job_id, None)
