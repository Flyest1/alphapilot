from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies import get_repository
from app.db.supabase_client import Repository
from app.services.report_service import ReportService

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _report_service(request: Request, repository: Repository) -> ReportService:
    market_data_service = getattr(request.app.state, "market_data_service", None)
    return ReportService(repository=repository, market_data_service=market_data_service)


@router.post("/domestic/generate")
def generate_domestic_report(
    request: Request,
    repository: Repository = Depends(get_repository),
) -> dict:
    if not request.app.state.rate_limiter.allow("/api/reports/domestic/generate"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded"
        )
    return _report_service(request, repository).generate_report("domestic")


@router.post("/global/generate")
def generate_global_report(
    request: Request,
    repository: Repository = Depends(get_repository),
) -> dict:
    if not request.app.state.rate_limiter.allow("/api/reports/global/generate"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded"
        )
    return _report_service(request, repository).generate_report("global")


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
