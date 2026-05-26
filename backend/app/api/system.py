from typing import Any
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from app.api.dependencies import get_repository
from app.config import get_environment_settings, is_supabase_configured
from app.db.supabase_client import Repository
from app.utils.logging import log_external_failure

router = APIRouter(prefix="/api/system", tags=["system"])
KST = ZoneInfo("Asia/Seoul")
SCHEDULE_GRACE_HOURS = 6


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
        "scheduler": {
            "domestic": _schedule_status(domestic_report, time(8, 30)),
            "global": _schedule_status(global_report, time(22, 30)),
        },
    }


def _schedule_status(latest_report: dict[str, Any] | None, target_time: time) -> dict[str, Any]:
    now = datetime.now(KST)
    expected = _last_expected_weekday_run(now, target_time)
    latest_created_at = _parse_datetime(latest_report.get("created_at")) if latest_report else None
    latest_kst = latest_created_at.astimezone(KST) if latest_created_at else None
    grace_cutoff = expected + timedelta(hours=SCHEDULE_GRACE_HOURS)
    is_ok = latest_kst is not None and latest_kst >= expected
    is_pending = latest_kst is None or latest_kst < expected
    status_label = "정상"
    status = "ok"
    if is_pending and now <= grace_cutoff:
        status = "pending"
        status_label = "대기"
    elif is_pending:
        status = "late"
        status_label = "지연"

    return {
        "status": status,
        "status_label": status_label,
        "last_expected_at": expected.isoformat(),
        "latest_created_at": latest_kst.isoformat() if latest_kst else None,
        "grace_hours": SCHEDULE_GRACE_HOURS,
        "note": "GitHub Actions scheduled workflows are best-effort and can be delayed.",
        "is_ok": is_ok,
    }


def _last_expected_weekday_run(now: datetime, target_time: time) -> datetime:
    candidate = datetime.combine(now.date(), target_time, tzinfo=KST)
    if now < candidate:
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
