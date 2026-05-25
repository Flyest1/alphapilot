from typing import Any

from fastapi import APIRouter, Depends

from app.api.dependencies import get_repository
from app.config import get_environment_settings, is_supabase_configured
from app.db.supabase_client import Repository
from app.utils.logging import log_external_failure

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status")
def get_system_status(repository: Repository = Depends(get_repository)) -> dict[str, Any]:
    env = get_environment_settings()
    openai_configured = bool(env.openai_api_key)
    supabase_configured = is_supabase_configured(env)

    try:
        assets = repository.list_assets()
        reports = repository.list_reports()
        candidates = repository.list_candidate_assets()
        domestic_report = repository.get_latest_report("domestic")
        global_report = repository.get_latest_report("global")
        database_status = "ok"
        database_error = None
    except Exception as exc:
        log_external_failure("system_status", exc, {"operation": "get_system_status"})
        assets = []
        reports = []
        candidates = []
        domestic_report = None
        global_report = None
        database_status = "error"
        database_error = "database check failed"

    active_candidates = [row for row in candidates if row.get("is_active", True)]

    return {
        "backend": {
            "status": "ok",
            "app_env": env.app_env,
        },
        "database": {
            "status": database_status,
            "provider": "supabase" if supabase_configured else "memory",
            "configured": supabase_configured,
            "error": database_error,
        },
        "openai": {
            "configured": openai_configured,
        },
        "assets": {
            "total_count": len(assets),
        },
        "candidate_assets": {
            "total_count": len(candidates),
            "active_count": len(active_candidates),
        },
        "reports": {
            "total_count": len(reports),
            "latest_domestic_created_at": (
                domestic_report.get("created_at") if domestic_report else None
            ),
            "latest_global_created_at": global_report.get("created_at") if global_report else None,
        },
    }
