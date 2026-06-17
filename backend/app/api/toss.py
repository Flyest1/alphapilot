from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_repository
from app.db.supabase_client import Repository
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
def sync_toss_holdings(repository: Repository = Depends(get_repository)) -> dict:
    try:
        return TossInvestService(repository).sync_holdings()
    except TossInvestConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except TossInvestError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
