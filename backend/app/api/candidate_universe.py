from typing import Any

from fastapi import APIRouter, Depends

from app.api.dependencies import get_repository
from app.db.supabase_client import Repository
from app.services.candidate_universe_service import CandidateUniverseService

router = APIRouter(prefix="/api/candidate-universe", tags=["candidate-universe"])


@router.post("/refresh")
def refresh_candidate_universe(
    repository: Repository = Depends(get_repository),
) -> dict[str, Any]:
    return CandidateUniverseService(repository).refresh()
