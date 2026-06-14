from typing import Any

from fastapi import APIRouter, Depends

from app.api.dependencies import get_repository
from app.db.supabase_client import Repository
from app.services.recommendation_stats_service import RecommendationStatsService

router = APIRouter(prefix="/api/recommendation-stats", tags=["recommendations"])


@router.get("")
def get_recommendation_stats(
    repository: Repository = Depends(get_repository),
) -> dict[str, Any]:
    return RecommendationStatsService(repository).compute_stats()
