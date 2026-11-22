from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_repository
from app.config import get_environment_settings, is_supabase_configured
from app.db.supabase_client import Repository
from app.utils.datetime import parse_iso_datetime
from app.utils.logging import log_external_failure

router = APIRouter(prefix="/api/system", tags=["system"])
KST = ZoneInfo("Asia/Seoul")
SCHEDULE_GRACE_HOURS = 6


@router.get("/status")
def get_system_status(
    request: Request,
    repository: Repository = Depends(get_repository),
) -> dict[str, Any]:
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
    now = datetime.now(KST)
    scheduler = {}
    schedule_errors = []
    for report_type, target_time, report in (
        ("domestic", time(8, 30), domestic_report),
        ("global", time(22, 30), global_report),
    ):
        expected = _last_expected_weekday_run(now, target_time)
        job, error = _safe_database_call(
            lambda: repository.latest_scheduled_job(report_type, expected, now),
            f"latest_scheduled_{report_type}_job",
            None,
        )
        schedule_errors.append(error)
        scheduler[report_type] = _schedule_status(job, expected, now, error)
        # Retain the latest report timestamp for clients of the original status endpoint.
        latest = parse_iso_datetime(report.get("created_at")) if report else None
        scheduler[report_type]["latest_created_at"] = (
            latest.astimezone(KST).isoformat() if latest else None
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
            *schedule_errors,
        )
        if error
    ]
    core_database_ok = asset_error is None and report_error is None
    database_status = "ok" if not database_errors else "partial" if core_database_ok else "error"
    database_error = "; ".join(database_errors) if database_errors else None

    active_candidates = [row for row in candidates if row.get("is_active", True)]
    report_generations = [_report_generation(row) for row in reports[:20]]
    filing_provider = getattr(request.app.state, "advisory_filing_provider", None)
    if filing_provider is None:
        sec_cache = {
            "status": "not_configured",
            "entry_count": 0,
            "size_bytes": 0,
            "max_entries": 0,
            "max_size_bytes": 0,
            "utilization_percent": 0.0,
        }
    else:
        try:
            sec_cache = filing_provider.cache_status()
        except Exception as exc:
            log_external_failure("system_status", exc, {"operation": "sec_cache_status"})
            sec_cache = {
                "status": "unavailable",
                "entry_count": 0,
                "size_bytes": 0,
                "max_entries": filing_provider.max_persistent_entries,
                "max_size_bytes": filing_provider.max_persistent_bytes,
                "utilization_percent": 0.0,
            }
    advisory_runner = getattr(request.app.state, "advisory_runner", None)
    advisory_runner_status = (
        advisory_runner.status()
        if advisory_runner is not None
        else {"active_count": 0, "queued_count": 0, "max_workers": 0}
    )

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
            "model": getattr(
                getattr(request.app.state, "application_settings", None),
                "ai_model",
                None,
            ),
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
                "cache": sec_cache,
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
        "scheduler": scheduler,
        "report_jobs": {
            "total_recent_count": len(report_jobs),
            "active_count": len(
                [row for row in report_jobs if row.get("status") in {"queued", "running"}]
            ),
            "latest": report_jobs[0] if report_jobs else None,
        },
        "advisory_jobs": advisory_runner_status,
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


def _schedule_status(
    job: dict[str, Any] | None, expected: datetime, now: datetime, error: str | None
) -> dict[str, Any]:
    cutoff = expected + timedelta(hours=SCHEDULE_GRACE_HOURS)
    received = parse_iso_datetime(job.get("created_at")) if job else None
    completed = None
    delay_minutes = None
    status, label = "unavailable", "확인 불가"
    if job is None and not error:
        status, label = ("pending", "접수 대기") if now <= cutoff else ("missing", "접수 누락")
    elif received is not None and received.tzinfo is not None:
        delay_minutes = int((received - expected).total_seconds() // 60)
        state = job.get("status")
        if state == "completed":
            updated = parse_iso_datetime(job.get("updated_at"))
            if updated and updated.tzinfo and received <= updated:
                completed = updated
                if delay_minutes > 0 or completed > cutoff:
                    status, label = "late_completed", "지연 완료"
                else:
                    status, label = "ok", "완료"
        elif state == "queued":
            status, label = "queued", "접수됨"
        elif state == "running":
            status, label = "running", "생성 중"
        elif state == "failed":
            status, label = "failed", "생성 실패"

    return {
        "status": status,
        "status_label": label,
        "last_expected_at": expected.isoformat(),
        "received_at": (
            received.astimezone(KST).isoformat() if received and received.tzinfo else None
        ),
        "completed_at": completed.astimezone(KST).isoformat() if completed else None,
        "receipt_delay_minutes": delay_minutes,
        "grace_hours": SCHEDULE_GRACE_HOURS,
        "note": "GitHub Actions scheduled workflows are best-effort and can be delayed.",
        "is_ok": status == "ok",
    }


def _last_expected_weekday_run(now: datetime, target_time: time) -> datetime:
    candidate = datetime.combine(now.date(), target_time, tzinfo=KST)
    if now < candidate:
        candidate -= timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate
