from typing import Any

from fastapi import APIRouter, Depends

from app.api.dependencies import get_repository
from app.db.supabase_client import Repository

router = APIRouter(prefix="/api/performance-logs", tags=["performance"])


@router.get("")
def list_performance_logs(repository: Repository = Depends(get_repository)) -> list[dict[str, Any]]:
    strategies = {row["id"]: row for row in repository.list_strategies()}
    rows = []
    for log_row in repository.list_performance_logs():
        strategy = strategies.get(log_row.get("strategy_id"), {})
        rows.append(
            {
                **log_row,
                "report_id": strategy.get("report_id"),
                "name": strategy.get("name"),
                "confidence": strategy.get("confidence"),
                "strategy_created_at": strategy.get("created_at"),
                "reasoning": strategy.get("reasoning"),
                "risk": strategy.get("risk"),
                "invalidation_condition": strategy.get("invalidation_condition"),
            }
        )
    return sorted(rows, key=lambda row: row.get("created_at") or "", reverse=True)
