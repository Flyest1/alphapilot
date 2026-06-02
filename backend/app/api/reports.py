from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from app.api.dependencies import get_repository
from app.db.supabase_client import Repository
from app.services.report_service import ReportService
from app.utils.logging import log_external_failure

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _run_manual_report_job(
    app_state: Any,
    repository: Repository,
    report_type: str,
    job_id: str,
) -> None:
    app_state.report_jobs.mark_running(job_id)
    try:
        report = ReportService(
            repository=repository,
            market_data_service=app_state.market_data_service,
            report_job_store=app_state.report_jobs,
            report_job_id=job_id,
        ).generate_report(report_type)
        app_state.report_jobs.mark_completed(job_id, report.get("id"))
    except Exception as exc:
        log_external_failure(
            "manual_report_job",
            exc,
            {"operation": "generate_report", "report_type": report_type, "job_id": job_id},
        )
        app_state.report_jobs.mark_failed(job_id, error_category="internal_error")


def _start_manual_report_job(
    report_type: str,
    endpoint_key: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    if not request.app.state.rate_limiter.allow(endpoint_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded"
        )
    job, created = request.app.state.report_jobs.create_or_get_active(report_type)
    if created:
        background_tasks.add_task(
            _run_manual_report_job,
            request.app.state,
            request.app.state.repository,
            report_type,
            job.job_id,
        )
    return job.to_dict()


@router.post("/domestic/generate", status_code=status.HTTP_202_ACCEPTED)
def generate_domestic_report(
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict:
    return _start_manual_report_job(
        "domestic",
        "/api/reports/domestic/generate",
        request,
        background_tasks,
    )


@router.post("/global/generate", status_code=status.HTTP_202_ACCEPTED)
def generate_global_report(
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict:
    return _start_manual_report_job(
        "global",
        "/api/reports/global/generate",
        request,
        background_tasks,
    )


@router.post("/domestic/manual-generate", status_code=status.HTTP_202_ACCEPTED)
def manually_generate_domestic_report(
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict:
    return _start_manual_report_job(
        "domestic",
        "/api/reports/domestic/manual-generate",
        request,
        background_tasks,
    )


@router.post("/global/manual-generate", status_code=status.HTTP_202_ACCEPTED)
def manually_generate_global_report(
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict:
    return _start_manual_report_job(
        "global",
        "/api/reports/global/manual-generate",
        request,
        background_tasks,
    )


@router.get("/manual-jobs/{job_id}")
def get_manual_report_job(job_id: str, request: Request) -> dict:
    job = request.app.state.report_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return job.to_dict()


@router.get("/latest")
def get_latest_reports(repository: Repository = Depends(get_repository)) -> dict:
    return {
        "domestic": repository.get_latest_report("domestic"),
        "global": repository.get_latest_report("global"),
    }


@router.get("")
def list_reports(repository: Repository = Depends(get_repository)) -> list[dict]:
    return repository.list_reports()


@router.get("/{report_id}")
def get_report(report_id: str, repository: Repository = Depends(get_repository)) -> dict:
    report = repository.get_report(report_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="report not found")
    report["strategies"] = repository.list_strategies(report_id)
    return report
