from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status

from app.models.advisory import (
    AdvisoryAnalysisResponse,
    AdvisoryJobRequest,
    AdvisoryJobResponse,
    AdvisoryStatusResponse,
    AnalysisType,
)
from app.services.advisory.job_service import is_advisory_migration_required, run_advisory_job

router = APIRouter(prefix="/api/advisory", tags=["advisory"])
MIGRATION_FILE = "backend/app/db/migrations/017_create_advisory_analyses.sql"


def _raise_advisory_storage_error(exc: Exception) -> None:
    if is_advisory_migration_required(exc):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "migration_required",
                "message": f"Supabase SQL Editor에서 {MIGRATION_FILE} 전체를 실행해 주세요.",
            },
        ) from exc
    raise exc


@router.get("/status", response_model=AdvisoryStatusResponse)
def get_advisory_status(request: Request) -> dict:
    try:
        request.app.state.advisory_jobs.list_analyses(limit=1)
        storage_status = "available"
    except Exception as exc:
        storage_status = (
            "migration_required" if is_advisory_migration_required(exc) else "unavailable"
        )
    return {
        "storage_status": storage_status,
        "ai_narrative_status": (
            "configured" if request.app.state.advisory_ai_narrative_configured else "not_configured"
        ),
        "migration_file": MIGRATION_FILE,
    }


@router.post("/jobs", response_model=AdvisoryJobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_advisory_job(
    payload: AdvisoryJobRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict:
    if not request.app.state.rate_limiter.allow("/api/advisory/jobs"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
        )
    try:
        job, created = request.app.state.advisory_jobs.create_or_get_active(payload)
    except Exception as exc:
        _raise_advisory_storage_error(exc)
    if created:
        background_tasks.add_task(
            run_advisory_job,
            request.app.state.advisory_jobs,
            request.app.state.advisory_dispatcher,
            job.job_id,
        )
    return job.to_dict()


@router.get("/jobs/{job_id}", response_model=AdvisoryJobResponse)
def get_advisory_job(job_id: str, request: Request) -> dict:
    try:
        job = request.app.state.advisory_jobs.get(job_id)
    except Exception as exc:
        _raise_advisory_storage_error(exc)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="advisory job not found")
    return job.to_dict()


@router.get("/analyses", response_model=list[AdvisoryAnalysisResponse])
def list_advisory_analyses(
    request: Request,
    analysis_type: AnalysisType | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[dict]:
    try:
        return [
            analysis.to_dict()
            for analysis in request.app.state.advisory_jobs.list_analyses(analysis_type, limit)
        ]
    except Exception as exc:
        _raise_advisory_storage_error(exc)


@router.get("/analyses/{analysis_id}", response_model=AdvisoryAnalysisResponse)
def get_advisory_analysis(analysis_id: str, request: Request) -> dict:
    try:
        analysis = request.app.state.advisory_jobs.get_analysis(analysis_id)
    except Exception as exc:
        _raise_advisory_storage_error(exc)
    if analysis is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="advisory analysis not found"
        )
    return analysis.to_dict()
