from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_repository
from app.db.supabase_client import Repository
from app.services.backtest_service import RuleBacktestService

router = APIRouter(prefix="/api/backtests", tags=["backtests"])


@router.post("/rules/run")
def run_rule_backtest(
    request: Request,
    report_type: Literal["domestic", "global"] = "global",
    limit: int = Query(default=12, ge=1, le=30),
    repository: Repository = Depends(get_repository),
) -> dict[str, Any]:
    return RuleBacktestService(
        repository,
        request.app.state.market_data_service,
    ).run(report_type=report_type, limit=limit)
