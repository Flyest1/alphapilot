from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_repository
from app.db.supabase_client import Repository
from app.models.portfolio import PortfolioSummaryResponse
from app.services.benchmark_service import BenchmarkService
from app.services.portfolio_service import PortfolioService

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.get("/summary", response_model=PortfolioSummaryResponse)
def get_portfolio_summary(
    request: Request,
    repository: Repository = Depends(get_repository),
) -> PortfolioSummaryResponse:
    market_data_service = getattr(request.app.state, "market_data_service", None)
    return PortfolioService(repository, market_data_service).get_summary()


@router.post("/snapshot")
def create_portfolio_snapshot(
    request: Request,
    repository: Repository = Depends(get_repository),
) -> dict:
    market_data_service = getattr(request.app.state, "market_data_service", None)
    return PortfolioService(repository, market_data_service).create_snapshot()


@router.get("/benchmark-returns")
def get_benchmark_returns(
    request: Request,
    days: int = 60,
    repository: Repository = Depends(get_repository),
) -> dict:
    market_data_service = getattr(request.app.state, "market_data_service", None)
    return BenchmarkService(repository, market_data_service).get_return_series(days)
