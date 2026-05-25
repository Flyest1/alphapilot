from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies import get_repository
from app.db.supabase_client import Repository
from app.services.report_service import ReportService

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _report_service(request: Request, repository: Repository) -> ReportService:
    market_data_service = getattr(request.app.state, "market_data_service", None)
    return ReportService(repository=repository, market_data_service=market_data_service)


def _generate_report(
    report_type: str,
    endpoint_key: str,
    request: Request,
    repository: Repository,
) -> dict:
    if not request.app.state.rate_limiter.allow(endpoint_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded"
        )
    return _report_service(request, repository).generate_report(report_type)


@router.post("/domestic/generate")
def generate_domestic_report(
    request: Request,
    repository: Repository = Depends(get_repository),
) -> dict:
    return _generate_report("domestic", "/api/reports/domestic/generate", request, repository)


@router.post("/global/generate")
def generate_global_report(
    request: Request,
    repository: Repository = Depends(get_repository),
) -> dict:
    return _generate_report("global", "/api/reports/global/generate", request, repository)


@router.post("/domestic/manual-generate")
def manually_generate_domestic_report(
    request: Request,
    repository: Repository = Depends(get_repository),
) -> dict:
    return _generate_report(
        "domestic", "/api/reports/domestic/manual-generate", request, repository
    )


@router.post("/global/manual-generate")
def manually_generate_global_report(
    request: Request,
    repository: Repository = Depends(get_repository),
) -> dict:
    return _generate_report("global", "/api/reports/global/manual-generate", request, repository)


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
