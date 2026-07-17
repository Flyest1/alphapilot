from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from app.api.dependencies import get_repository
from app.config import get_environment_settings, is_supabase_configured
from app.db.supabase_client import Repository
from app.utils.datetime import parse_iso_datetime
from app.utils.logging import log_external_failure

router = APIRouter(prefix="/api/system", tags=["system"])
KST = ZoneInfo("Asia/Seoul")
SCHEDULE_GRACE_HOURS = 6


@router.get("/status")
def get_system_status(repository: Repository = Depends(get_repository)) -> dict[str, Any]:
    env = get_environment_settings()
    openai_configured = bool(env.openai_api_key)
    supabase_configured = is_supabase_configured(env)
    security_warnings = []
    if (
        env.api_access_token
        and env.scheduler_secret
        and env.api_access_token == env.scheduler_secret
    ):
        security_warnings.append("API_ACCESS_TOKEN and SCHEDULER_SECRET must be different values.")

    assets, asset_error = _safe_database_call(repository.list_assets, "list_assets", [])
    reports, report_error = _safe_database_call(repository.list_reports, "list_reports", [])
    candidates, candidate_error = _safe_database_call(
        repository.list_candidate_assets, "list_candidate_assets", []
    )
    domestic_report, domestic_error = _safe_database_call(
        lambda: repository.get_latest_report("domestic"),
        "get_latest_domestic_report",
        None,
    )
    global_report, global_error = _safe_database_call(
        lambda: repository.get_latest_report("global"),
        "get_latest_global_report",
        None,
    )
    report_jobs, report_job_error = _safe_database_call(
        lambda: repository.list_report_jobs(limit=20),
        "list_report_jobs",
        [],
    )
    snapshots, snapshot_error = _safe_database_call(
        lambda: repository.list_portfolio_snapshots(limit=20),
        "list_portfolio_snapshots",
        [],
    )
    recommendation_cycles, cycle_error = _safe_database_call(
        lambda: repository.list_recommendation_cycles(limit=50),
        "list_recommendation_cycles",
        [],
    )
    database_errors = [
        error
        for error in (
            asset_error,
            report_error,
            candidate_error,
            domestic_error,
            global_error,
            report_job_error,
            snapshot_error,
            cycle_error,
        )
        if error
    ]
    core_database_ok = asset_error is None and report_error is None
    database_status = "ok" if not database_errors else "partial" if core_database_ok else "error"
    database_error = "; ".join(database_errors) if database_errors else None

    active_candidates = [row for row in candidates if row.get("is_active", True)]
    report_generations = [_report_generation(row) for row in reports[:20]]

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
        "security": {
            "tokens_distinct": not security_warnings,
            "warnings": security_warnings,
        },
        "openai": {
            "configured": openai_configured,
            "latest_domestic_generation": _report_generation(domestic_report),
            "latest_global_generation": _report_generation(global_report),
            "recent_technical_only_count": sum(
                generation.get("mode") == "technical_only" for generation in report_generations
            ),
        },
        "data_providers": {
            "sec_edgar": {
                "configured": bool(env.sec_edgar_user_agent),
                "mode": "read_only",
            },
            "fred": {
                "configured": bool(env.fred_api_key),
                "mode": "read_only",
            },
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
        "report_jobs": {
            "total_recent_count": len(report_jobs),
            "active_count": len(
                [row for row in report_jobs if row.get("status") in {"queued", "running"}]
            ),
            "latest": report_jobs[0] if report_jobs else None,
        },
        "portfolio_snapshots": {
            "recent_count": len(snapshots),
            "latest_created_at": snapshots[0].get("created_at") if snapshots else None,
        },
        "recommendation_cycles": {
            "recent_count": len(recommendation_cycles),
            "active_count": len(
                [row for row in recommendation_cycles if row.get("status") == "active"]
            ),
        },
    }


def _safe_database_call(func: Any, operation: str, fallback: Any) -> tuple[Any, str | None]:
    try:
        return func(), None
    except Exception as exc:
        log_external_failure("system_status", exc, {"operation": operation})
        return fallback, f"{operation} failed"


def _report_generation(report: dict[str, Any] | None) -> dict[str, Any]:
    if not report:
        return {"mode": "not_generated", "fallback_reason": None}
    generation = ((report.get("report_inputs") or {}).get("ai_generation") or {}).copy()
    if generation:
        return generation
    content = report.get("content") or {}
    technical_only = "AI reasoning unavailable for this report" in (content.get("key_risks") or [])
    return {
        "mode": "technical_only" if technical_only else "legacy_unknown",
        "fallback_reason": "legacy_inference" if technical_only else None,
    }


def _schedule_status(latest_report: dict[str, Any] | None, target_time: time) -> dict[str, Any]:
    now = datetime.now(KST)
    expected = _last_expected_weekday_run(now, target_time)
    latest_created_at = (
        parse_iso_datetime(latest_report.get("created_at")) if latest_report else None
    )
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
