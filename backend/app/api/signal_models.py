from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_repository
from app.db.supabase_client import Repository
from app.models.signal_model import SignalModelEvaluationResponse
from app.services.signal_model_evaluation_service import (
    SignalModelEvaluationService,
    SignalModelEvaluationUnavailableError,
)

router = APIRouter(prefix="/api/signal-models", tags=["signal-models"])


@router.get("/evaluation", response_model=SignalModelEvaluationResponse)
def get_signal_model_evaluation(
    repository: Repository = Depends(get_repository),
) -> SignalModelEvaluationResponse:
    try:
        return SignalModelEvaluationService(repository).get_evaluation()
    except SignalModelEvaluationUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="signal model evaluation storage is unavailable",
        ) from exc
