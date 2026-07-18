import logging
import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    advisory,
    assets,
    backtests,
    candidate_universe,
    candidates,
    notifications,
    performance,
    portfolio,
    recommendation_stats,
    recommendations,
    reports,
    settings,
    signal_models,
    system,
    toss,
)
from app.config import (
    get_env_application_defaults,
    get_environment_settings,
    resolve_application_settings,
)
from app.db.supabase_client import Repository, create_repository
from app.services.advisory.job_service import (
    AdvisoryDispatcher,
    AdvisoryJobRunner,
    AdvisoryJobStore,
)
from app.services.advisory.openai_provider import OpenAIAdvisoryProvider
from app.services.advisory.pipeline import AdvisoryPipeline
from app.services.advisory.providers.fred import FredMacroProvider
from app.services.advisory.providers.sec_edgar import (
    SEC_DEFAULT_MAX_PERSISTENT_BYTES,
    SecEdgarProvider,
)
from app.services.market_data_service import MarketDataService
from app.services.news_service import NewsService
from app.services.report_job_service import ReportJobStore
from app.utils.rate_limit import DailyEndpointRateLimiter

SCHEDULER_ENDPOINTS = {
    "/api/candidate-universe/refresh",
    "/api/reports/domestic/generate",
    "/api/reports/global/generate",
}
LEGACY_DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
CURRENT_DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    prefix = "Bearer "
    if not header.startswith(prefix):
        return None
    token = header[len(prefix) :].strip()
    return token or None


def _cors_headers_for_request(request: Request) -> dict[str, str]:
    env = get_environment_settings()
    origin = request.headers.get("origin")
    if origin and origin in _frontend_origins(env.frontend_origin):
        return {
            "Access-Control-Allow-Origin": origin,
            "Vary": "Origin",
        }
    return {}


def _frontend_origins(frontend_origin: str | None) -> list[str]:
    if not frontend_origin:
        return []
    return [origin.strip().rstrip("/") for origin in frontend_origin.split(",") if origin.strip()]


def _upgrade_legacy_ai_model(
    repository: Repository,
    stored_settings: dict | None,
    app_defaults: dict[str, Any],
) -> tuple[dict | None, dict[str, Any]]:
    if app_defaults.get("ai_model") == LEGACY_DEFAULT_OPENAI_MODEL:
        app_defaults = {**app_defaults, "ai_model": CURRENT_DEFAULT_OPENAI_MODEL}
    if not stored_settings or stored_settings.get("ai_model") != LEGACY_DEFAULT_OPENAI_MODEL:
        return stored_settings, app_defaults
    try:
        stored_settings = repository.upsert_settings({"ai_model": CURRENT_DEFAULT_OPENAI_MODEL})
    except Exception:
        logging.getLogger("alphapilot").exception("legacy AI model upgrade failed at startup")
    return stored_settings, app_defaults


@asynccontextmanager
async def _advisory_job_lifespan(app: FastAPI):
    app.state.advisory_runner = AdvisoryJobRunner(
        app.state.advisory_jobs,
        app.state.advisory_dispatcher,
    )
    try:
        job_ids = app.state.advisory_jobs.recover_unfinished_jobs()
    except Exception:
        logging.getLogger("alphapilot").exception("advisory job recovery scan failed")
    else:
        for job_id in job_ids:
            app.state.advisory_runner.submit(job_id)
    try:
        yield
    finally:
        app.state.advisory_runner.shutdown()


def create_app(repository: Repository | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO)
    env = get_environment_settings()
    app = FastAPI(title="AlphaPilot API", version="0.1.0", lifespan=_advisory_job_lifespan)
    app.state.repository = repository or create_repository(env)
    app.state.rate_limiter = DailyEndpointRateLimiter(max_per_day=10)
    app.state.market_data_service = MarketDataService(repository=app.state.repository)
    app.state.news_service = NewsService()
    app.state.report_jobs = ReportJobStore(app.state.repository)
    app.state.advisory_jobs = AdvisoryJobStore(app.state.repository)
    app_defaults = get_env_application_defaults()
    try:
        stored_settings = app.state.repository.get_settings()
    except Exception:
        logging.getLogger("alphapilot").exception("application settings lookup failed at startup")
        stored_settings = None
    stored_settings, app_defaults = _upgrade_legacy_ai_model(
        app.state.repository,
        stored_settings,
        app_defaults,
    )
    application_settings = resolve_application_settings(stored_settings, app_defaults)
    app.state.application_settings = application_settings
    narrative_provider = (
        OpenAIAdvisoryProvider(
            env.openai_api_key,
            application_settings.ai_model,
        )
        if env.openai_api_key
        else None
    )
    filing_provider = (
        SecEdgarProvider(
            user_agent=env.sec_edgar_user_agent,
            timeout_seconds=8,
            max_retries=2,
            max_persistent_bytes=(
                env.sec_edgar_cache_max_bytes
                if env.sec_edgar_cache_max_bytes is not None
                else SEC_DEFAULT_MAX_PERSISTENT_BYTES
            ),
        )
        if env.sec_edgar_user_agent
        else None
    )
    macro_provider = (
        FredMacroProvider(
            api_key=env.fred_api_key,
            timeout_seconds=8,
            max_attempts=2,
        )
        if env.fred_api_key
        else None
    )
    advisory_pipeline = AdvisoryPipeline(
        app.state.repository,
        app.state.market_data_service,
        filing_provider=filing_provider,
        macro_provider=macro_provider,
        news_service=app.state.news_service,
        narrative_provider=narrative_provider,
    )
    app.state.advisory_sec_edgar_configured = filing_provider is not None
    app.state.advisory_filing_provider = filing_provider
    app.state.advisory_fred_configured = macro_provider is not None
    app.state.advisory_ai_narrative_configured = narrative_provider is not None
    app.state.advisory_narrative_provider = narrative_provider
    app.state.advisory_dispatcher = AdvisoryDispatcher(advisory_pipeline.handlers())

    origins = _frontend_origins(env.frontend_origin)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.middleware("http")
    async def api_token_middleware(request: Request, call_next: Callable) -> JSONResponse:
        if request.method == "OPTIONS" or not request.url.path.startswith("/api/"):
            return await call_next(request)

        current_env = get_environment_settings()
        expected_token = (
            current_env.scheduler_secret
            if request.url.path in SCHEDULER_ENDPOINTS
            else current_env.api_access_token
        )
        provided_token = _bearer_token(request)
        if (
            not expected_token
            or provided_token is None
            or not secrets.compare_digest(provided_token.encode(), expected_token.encode())
        ):
            return JSONResponse(
                {"detail": "unauthorized"},
                status_code=401,
                headers=_cors_headers_for_request(request),
            )
        return await call_next(request)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger("alphapilot").exception(
            "unhandled exception",
            extra={"path": request.url.path, "method": request.method, "error": str(exc)},
        )
        return JSONResponse({"detail": "internal server error"}, status_code=500)

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "service": "alphapilot-backend",
            "status": "ok",
            "health": "/health",
        }

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(assets.router)
    app.include_router(advisory.router)
    app.include_router(backtests.router)
    app.include_router(candidate_universe.router)
    app.include_router(candidates.router)
    app.include_router(notifications.router)
    app.include_router(performance.router)
    app.include_router(portfolio.router)
    app.include_router(recommendation_stats.router)
    app.include_router(recommendations.router)
    app.include_router(reports.router)
    app.include_router(settings.router)
    app.include_router(signal_models.router)
    app.include_router(system.router)
    app.include_router(toss.router)
    return app


app = create_app()
