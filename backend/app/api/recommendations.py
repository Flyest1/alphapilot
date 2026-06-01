from typing import Any

from fastapi import APIRouter, Depends

from app.api.dependencies import get_repository
from app.db.supabase_client import Repository

router = APIRouter(prefix="/api/recommendation-cycles", tags=["recommendations"])


@router.get("")
def list_recommendation_cycles(
    repository: Repository = Depends(get_repository),
) -> list[dict[str, Any]]:
    return repository.list_recommendation_cycles(limit=500)
