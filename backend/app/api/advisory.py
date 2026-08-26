from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.models.advisory import (
    AdvisoryAnalysisResponse,
    AdvisoryJobRequest,
    AdvisoryJobResponse,
    AdvisoryStatusResponse,
    AnalysisType,
)
from app.services.advisory.job_service import (
    AdvisoryJobRunner,
    is_advisory_migration_required,
    is_profit_taking_review_migration_required,
)

router = APIRouter(prefix="/api/advisory", tags=["advisory"])
MIGRATION_FILE = "backend/app/db/migrations/017_create_advisory_analyses.sql"
PROFIT_TAKING_REVIEW_MIGRATION_FILE = (
    "backend/app/db/migrations/020_add_profit_taking_review_advisory.sql"
)
HIGH_UPSIDE_SPECULATIVE_STOCKS_MIGRATION_FILE = (
    "backend/app/db/migrations/021_add_high_upside_speculative_stocks_advisory.sql"
)


def _raise_advisory_storage_error(
    exc: Exception, analysis_type: AnalysisType | None = None
) -> None:
    if is_advisory_migration_required(exc):
        if analysis_type == "high_upside_speculative_stocks":
            migration_file = HIGH_UPSIDE_SPECULATIVE_STOCKS_MIGRATION_FILE
        elif analysis_type == "profit_taking_review" or is_profit_taking_review_migration_required(
            exc
        ):
            migration_file = PROFIT_TAKING_REVIEW_MIGRATION_FILE
        else:
            migration_file = MIGRATION_FILE
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "migration_required",
                "message": f"Supabase SQL Editor에서 {migration_file} 전체를 실행해 주세요.",
            },
        ) from exc
    raise exc


@router.get("/status", response_model=AdvisoryStatusResponse)
def get_advisory_status(request: Request) -> dict:
    try:
        request.app.state.advisory_jobs.check_storage()
        storage_status = "available"
    except Exception as exc:
        storage_status = (
            "migration_required" if is_advisory_migration_required(exc) else "unavailable"
        )
    profit_taking_review_status = "unavailable"
    if storage_status == "available":
        try:
            profit_taking_review_status = (
                "available"
                if request.app.state.advisory_jobs.has_capability("profit_taking_review")
                else "migration_required"
            )
        except Exception as exc:
            profit_taking_review_status = (
                "migration_required"
                if is_profit_taking_review_migration_required(exc)
                else "unavailable"
            )
    elif storage_status == "migration_required":
        profit_taking_review_status = "migration_required"
    high_upside_status = "unavailable"
    if storage_status == "available":
        try:
            high_upside_status = (
                "available"
                if request.app.state.advisory_jobs.has_capability("high_upside_speculative_stocks")
                else "migration_required"
            )
        except Exception as exc:
            high_upside_status = (
                "migration_required"
                if is_profit_taking_review_migration_required(exc)
                else "unavailable"
            )
    elif storage_status == "migration_required":
        high_upside_status = "migration_required"
    return {
        "storage_status": storage_status,
        "ai_narrative_status": (
            "configured" if request.app.state.advisory_ai_narrative_configured else "not_configured"
        ),
        "migration_file": MIGRATION_FILE,
        "profit_taking_review_status": profit_taking_review_status,
        "profit_taking_review_migration_file": PROFIT_TAKING_REVIEW_MIGRATION_FILE,
        "high_upside_speculative_stocks_status": high_upside_status,
        "high_upside_speculative_stocks_migration_file": (
            HIGH_UPSIDE_SPECULATIVE_STOCKS_MIGRATION_FILE
        ),
    }


@router.post("/jobs", response_model=AdvisoryJobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_advisory_job(
    payload: AdvisoryJobRequest,
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
        _raise_advisory_storage_error(exc, payload.analysis_type)
    if created:
        runner = getattr(request.app.state, "advisory_runner", None)
        if runner is None:
            runner = AdvisoryJobRunner(
                request.app.state.advisory_jobs,
                request.app.state.advisory_dispatcher,
            )
            request.app.state.advisory_runner = runner
        runner.submit(job.job_id)
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
