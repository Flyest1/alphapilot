from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.dependencies import get_repository
from app.db.supabase_client import Repository
from app.services.report_job_service import ReportGenerationLockTimeout
from app.services.toss_invest_service import (
    TossInvestConfigurationError,
    TossInvestError,
    TossInvestService,
)

router = APIRouter(prefix="/api/toss", tags=["toss"])


@router.get("/status")
def get_toss_status(repository: Repository = Depends(get_repository)) -> dict:
    return TossInvestService(repository).status()


@router.post("/sync")
def sync_toss_holdings(
    request: Request,
    repository: Repository = Depends(get_repository),
) -> dict:
    try:
        with request.app.state.report_jobs.serialize_generation(wait_timeout_seconds=0):
            return TossInvestService(repository).sync_holdings()
    except ReportGenerationLockTimeout as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="report generation or Toss sync is already in progress",
        ) from exc
    except TossInvestConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except TossInvestError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
