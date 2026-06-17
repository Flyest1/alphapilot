from collections.abc import Iterable
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import EnvironmentSettings, get_environment_settings, is_supabase_configured
from app.utils.logging import log_external_failure


class Repository(Protocol):
    def list_assets(self) -> list[dict[str, Any]]: ...

    def get_asset(self, asset_id: str) -> dict[str, Any] | None: ...

    def create_asset(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def update_asset(self, asset_id: str, data: dict[str, Any]) -> dict[str, Any] | None: ...

    def delete_asset(self, asset_id: str) -> bool: ...

    def get_asset_by_external_key(
        self,
        provider: str,
        account_id: str,
        asset_key: str,
    ) -> dict[str, Any] | None: ...

    def upsert_external_asset(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def list_candidate_assets(self) -> list[dict[str, Any]]: ...

    def get_candidate_asset(self, candidate_id: str) -> dict[str, Any] | None: ...

    def create_candidate_asset(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def update_candidate_asset(
        self, candidate_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    def delete_candidate_asset(self, candidate_id: str) -> bool: ...

    def list_candidate_universe(self, report_type: str | None = None) -> list[dict[str, Any]]: ...

    def upsert_candidate_universe(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def get_settings(self) -> dict[str, Any] | None: ...

    def upsert_settings(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def list_reports(self) -> list[dict[str, Any]]: ...

    def get_report(self, report_id: str) -> dict[str, Any] | None: ...

    def get_latest_report(self, report_type: str | None = None) -> dict[str, Any] | None: ...

    def create_report(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def create_strategy(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def list_strategies(self, report_id: str | None = None) -> list[dict[str, Any]]: ...

    def create_performance_log(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def list_performance_logs(self, limit: int | None = None) -> list[dict[str, Any]]: ...

    def list_unevaluated_performance_logs(
        self, limit: int | None = None
    ) -> list[dict[str, Any]]: ...

    def update_performance_log(
        self, log_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    def create_report_job(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def update_report_job(self, job_id: str, data: dict[str, Any]) -> dict[str, Any] | None: ...

    def get_report_job(self, job_id: str) -> dict[str, Any] | None: ...

    def list_report_jobs(
        self, status: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]: ...

    def create_portfolio_snapshot(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def list_portfolio_snapshots(self, limit: int | None = None) -> list[dict[str, Any]]: ...

    def create_recommendation_cycle(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def update_recommendation_cycle(
        self, cycle_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    def list_recommendation_cycles(
        self, status: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]: ...

    def list_open_recommendation_cycles(self, limit: int | None = None) -> list[dict[str, Any]]: ...

    def get_market_data_cache(self, cache_key: str) -> dict[str, Any] | None: ...

    def upsert_market_data_cache(self, cache_key: str, payload: dict[str, Any]) -> None: ...

    def list_notifications(
        self, unread_only: bool = False, limit: int | None = None
    ) -> list[dict[str, Any]]: ...

    def get_notification_by_event_key(self, event_key: str) -> dict[str, Any] | None: ...

    def create_notification(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def update_notification(
        self, notification_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    def mark_all_notifications_read(self) -> int: ...


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _copy_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [deepcopy(row) for row in rows]


class InMemoryRepository:
    def __init__(self) -> None:
        self.assets: dict[str, dict[str, Any]] = {}
        self.candidate_assets: dict[str, dict[str, Any]] = {}
        self.candidate_universe: dict[str, dict[str, Any]] = {}
        self.settings: dict[str, Any] | None = None
        self.reports: dict[str, dict[str, Any]] = {}
        self.strategies: dict[str, dict[str, Any]] = {}
        self.performance_logs: dict[str, dict[str, Any]] = {}
        self.report_jobs: dict[str, dict[str, Any]] = {}
        self.portfolio_snapshots: dict[str, dict[str, Any]] = {}
        self.recommendation_cycles: dict[str, dict[str, Any]] = {}
        self.market_data_cache: dict[str, dict[str, Any]] = {}
        self.notifications: dict[str, dict[str, Any]] = {}

    def list_assets(self) -> list[dict[str, Any]]:
        return sorted(_copy_rows(self.assets.values()), key=lambda row: row["created_at"])

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        row = self.assets.get(asset_id)
        return deepcopy(row) if row else None

    def create_asset(self, data: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(data)
        row["id"] = row.get("id") or str(uuid4())
        now = _now_iso()
        row["created_at"] = row.get("created_at") or now
        row["updated_at"] = row.get("updated_at") or now
        self.assets[row["id"]] = row
        return deepcopy(row)

    def update_asset(self, asset_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        if asset_id not in self.assets:
            return None
        clean_data = {key: value for key, value in data.items() if value is not None}
        self.assets[asset_id].update(clean_data)
        self.assets[asset_id]["updated_at"] = _now_iso()
        return deepcopy(self.assets[asset_id])

    def delete_asset(self, asset_id: str) -> bool:
        return self.assets.pop(asset_id, None) is not None

    def get_asset_by_external_key(
        self,
        provider: str,
        account_id: str,
        asset_key: str,
    ) -> dict[str, Any] | None:
        for row in self.assets.values():
            if (
                row.get("external_provider") == provider
                and row.get("external_account_id") == account_id
                and row.get("external_asset_key") == asset_key
            ):
                return deepcopy(row)
        return None

    def upsert_external_asset(self, data: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_asset_by_external_key(
            str(data.get("external_provider") or ""),
            str(data.get("external_account_id") or ""),
            str(data.get("external_asset_key") or ""),
        )
        if existing:
            return self.update_asset(existing["id"], data) or existing
        return self.create_asset(data)

    def list_candidate_assets(self) -> list[dict[str, Any]]:
        return sorted(_copy_rows(self.candidate_assets.values()), key=lambda row: row["created_at"])

    def get_candidate_asset(self, candidate_id: str) -> dict[str, Any] | None:
        row = self.candidate_assets.get(candidate_id)
        return deepcopy(row) if row else None

    def create_candidate_asset(self, data: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(data)
        row["id"] = row.get("id") or str(uuid4())
        now = _now_iso()
        row["created_at"] = row.get("created_at") or now
        row["updated_at"] = row.get("updated_at") or now
        row["is_active"] = row.get("is_active", True)
        self.candidate_assets[row["id"]] = row
        return deepcopy(row)

    def update_candidate_asset(
        self, candidate_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        if candidate_id not in self.candidate_assets:
            return None
        clean_data = {key: value for key, value in data.items() if value is not None}
        self.candidate_assets[candidate_id].update(clean_data)
        self.candidate_assets[candidate_id]["updated_at"] = _now_iso()
        return deepcopy(self.candidate_assets[candidate_id])

    def delete_candidate_asset(self, candidate_id: str) -> bool:
        return self.candidate_assets.pop(candidate_id, None) is not None

    def list_candidate_universe(self, report_type: str | None = None) -> list[dict[str, Any]]:
        rows = [
            row
            for row in _copy_rows(self.candidate_universe.values())
            if row.get("is_active", True)
            and (report_type is None or row.get("report_type") == report_type)
        ]
        return sorted(
            rows,
            key=lambda row: (
                row.get("report_type") or "",
                row.get("source_rank") if row.get("source_rank") is not None else 999999,
                row.get("ticker") or "",
            ),
        )

    def upsert_candidate_universe(self, data: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(data)
        key = f"{row['market']}:{row['ticker']}"
        existing = self.candidate_universe.get(key, {})
        now = _now_iso()
        row["id"] = existing.get("id") or row.get("id") or str(uuid4())
        row["created_at"] = existing.get("created_at") or row.get("created_at") or now
        row["updated_at"] = now
        row["refreshed_at"] = row.get("refreshed_at") or now
        row["is_active"] = row.get("is_active", True)
        self.candidate_universe[key] = {**existing, **row}
        return deepcopy(self.candidate_universe[key])

    def get_settings(self) -> dict[str, Any] | None:
        return deepcopy(self.settings) if self.settings else None

    def upsert_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        now = _now_iso()
        if self.settings is None:
            self.settings = {"id": str(uuid4()), "created_at": now}
        self.settings.update({key: value for key, value in data.items() if value is not None})
        self.settings["updated_at"] = now
        return deepcopy(self.settings)

    def list_reports(self) -> list[dict[str, Any]]:
        return sorted(
            _copy_rows(self.reports.values()),
            key=lambda row: row["created_at"],
            reverse=True,
        )

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        row = self.reports.get(report_id)
        return deepcopy(row) if row else None

    def get_latest_report(self, report_type: str | None = None) -> dict[str, Any] | None:
        reports = self.list_reports()
        if report_type is not None:
            reports = [row for row in reports if row.get("report_type") == report_type]
        return reports[0] if reports else None

    def create_report(self, data: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(data)
        row["id"] = row.get("id") or str(uuid4())
        row["created_at"] = row.get("created_at") or _now_iso()
        self.reports[row["id"]] = row
        return deepcopy(row)

    def create_strategy(self, data: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(data)
        row["id"] = row.get("id") or str(uuid4())
        row["created_at"] = row.get("created_at") or _now_iso()
        self.strategies[row["id"]] = row
        return deepcopy(row)

    def list_strategies(self, report_id: str | None = None) -> list[dict[str, Any]]:
        rows = _copy_rows(self.strategies.values())
        if report_id is not None:
            rows = [row for row in rows if row.get("report_id") == report_id]
        return sorted(rows, key=lambda row: row["created_at"], reverse=True)

    def create_performance_log(self, data: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(data)
        row["id"] = row.get("id") or str(uuid4())
        row["created_at"] = row.get("created_at") or _now_iso()
        self.performance_logs[row["id"]] = row
        return deepcopy(row)

    def list_performance_logs(self, limit: int | None = None) -> list[dict[str, Any]]:
        rows = _copy_rows(self.performance_logs.values())
        rows = sorted(rows, key=lambda row: row.get("created_at") or "", reverse=True)
        return rows[:limit] if limit is not None else rows

    def list_unevaluated_performance_logs(self, limit: int | None = None) -> list[dict[str, Any]]:
        rows = [
            row
            for row in _copy_rows(self.performance_logs.values())
            if row.get("price_after_20d") is None
        ]
        rows = sorted(rows, key=lambda row: row.get("created_at") or "", reverse=True)
        return rows[:limit] if limit is not None else rows

    def update_performance_log(self, log_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        if log_id not in self.performance_logs:
            return None
        self.performance_logs[log_id].update(
            {key: value for key, value in data.items() if value is not None}
        )
        return deepcopy(self.performance_logs[log_id])

    def create_report_job(self, data: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(data)
        row["job_id"] = row.get("job_id") or str(uuid4())
        now = _now_iso()
        row["created_at"] = row.get("created_at") or now
        row["updated_at"] = row.get("updated_at") or now
        row["step_timings"] = row.get("step_timings") or {}
        self.report_jobs[row["job_id"]] = row
        return deepcopy(row)

    def update_report_job(self, job_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        if job_id not in self.report_jobs:
            return None
        self.report_jobs[job_id].update(
            {key: value for key, value in data.items() if value is not None}
        )
        self.report_jobs[job_id]["updated_at"] = _now_iso()
        return deepcopy(self.report_jobs[job_id])

    def get_report_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.report_jobs.get(job_id)
        return deepcopy(row) if row else None

    def list_report_jobs(
        self, status: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        rows = _copy_rows(self.report_jobs.values())
        if status is not None:
            rows = [row for row in rows if row.get("status") == status]
        rows = sorted(rows, key=lambda row: row.get("created_at") or "", reverse=True)
        return rows[:limit] if limit is not None else rows

    def create_portfolio_snapshot(self, data: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(data)
        row["id"] = row.get("id") or str(uuid4())
        row["created_at"] = row.get("created_at") or _now_iso()
        self.portfolio_snapshots[row["id"]] = row
        return deepcopy(row)

    def list_portfolio_snapshots(self, limit: int | None = None) -> list[dict[str, Any]]:
        rows = _copy_rows(self.portfolio_snapshots.values())
        rows = sorted(rows, key=lambda row: row.get("created_at") or "", reverse=True)
        return rows[:limit] if limit is not None else rows

    def create_recommendation_cycle(self, data: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(data)
        row["id"] = row.get("id") or str(uuid4())
        now = _now_iso()
        row["created_at"] = row.get("created_at") or now
        row["updated_at"] = row.get("updated_at") or now
        row["started_at"] = row.get("started_at") or now
        row["metadata"] = row.get("metadata") or {}
        self.recommendation_cycles[row["id"]] = row
        return deepcopy(row)

    def update_recommendation_cycle(
        self, cycle_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        if cycle_id not in self.recommendation_cycles:
            return None
        self.recommendation_cycles[cycle_id].update(
            {key: value for key, value in data.items() if value is not None}
        )
        self.recommendation_cycles[cycle_id]["updated_at"] = _now_iso()
        return deepcopy(self.recommendation_cycles[cycle_id])

    def list_recommendation_cycles(
        self, status: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        rows = _copy_rows(self.recommendation_cycles.values())
        if status is not None:
            rows = [row for row in rows if row.get("status") == status]
        rows = sorted(rows, key=lambda row: row.get("created_at") or "", reverse=True)
        return rows[:limit] if limit is not None else rows

    def list_open_recommendation_cycles(self, limit: int | None = None) -> list[dict[str, Any]]:
        rows = [
            row
            for row in _copy_rows(self.recommendation_cycles.values())
            if row.get("status") == "active" or row.get("price_after_60d") is None
        ]
        rows = sorted(rows, key=lambda row: row.get("created_at") or "", reverse=True)
        return rows[:limit] if limit is not None else rows

    def get_market_data_cache(self, cache_key: str) -> dict[str, Any] | None:
        row = self.market_data_cache.get(cache_key)
        return deepcopy(row) if row else None

    def upsert_market_data_cache(self, cache_key: str, payload: dict[str, Any]) -> None:
        self.market_data_cache[cache_key] = {
            "cache_key": cache_key,
            "payload": deepcopy(payload),
            "created_at": _now_iso(),
        }

    def list_notifications(
        self, unread_only: bool = False, limit: int | None = None
    ) -> list[dict[str, Any]]:
        rows = _copy_rows(self.notifications.values())
        if unread_only:
            rows = [row for row in rows if not row.get("is_read", False)]
        rows = sorted(rows, key=lambda row: row.get("created_at") or "", reverse=True)
        return rows[:limit] if limit is not None else rows

    def get_notification_by_event_key(self, event_key: str) -> dict[str, Any] | None:
        row = next(
            (row for row in self.notifications.values() if row.get("event_key") == event_key),
            None,
        )
        return deepcopy(row) if row else None

    def create_notification(self, data: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(data)
        row["id"] = row.get("id") or str(uuid4())
        now = _now_iso()
        row["created_at"] = row.get("created_at") or now
        row["updated_at"] = row.get("updated_at") or now
        row["is_read"] = row.get("is_read", False)
        row["metadata"] = row.get("metadata") or {}
        row["telegram_status"] = row.get("telegram_status") or "not_requested"
        self.notifications[row["id"]] = row
        return deepcopy(row)

    def update_notification(
        self, notification_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        if notification_id not in self.notifications:
            return None
        self.notifications[notification_id].update(data)
        self.notifications[notification_id]["updated_at"] = _now_iso()
        return deepcopy(self.notifications[notification_id])

    def mark_all_notifications_read(self) -> int:
        now = _now_iso()
        updated = 0
        for row in self.notifications.values():
            if row.get("is_read"):
                continue
            row["is_read"] = True
            row["read_at"] = now
            row["updated_at"] = now
            updated += 1
        return updated


class SupabaseRepository:
    def __init__(self, env: EnvironmentSettings | None = None, client: Any | None = None) -> None:
        current_env = env or get_environment_settings()
        if client is None:
            from supabase import create_client

            if not current_env.supabase_url or not current_env.supabase_service_role_key:
                raise RuntimeError("Supabase configuration is missing")
            client = create_client(current_env.supabase_url, current_env.supabase_service_role_key)
        self.client = client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=True,
    )
    def _execute(self, builder: Any) -> Any:
        return builder.execute()

    def _run(self, builder: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            response = self._execute(builder)
            return list(response.data or [])
        except Exception as exc:
            log_external_failure("supabase", exc, context)
            raise

    def list_assets(self) -> list[dict[str, Any]]:
        builder = self.client.table("assets").select("*").order("created_at")
        return self._run(builder, {"operation": "list_assets"})

    def get_asset(self, asset_id: str) -> dict[str, Any] | None:
        builder = self.client.table("assets").select("*").eq("id", asset_id).limit(1)
        rows = self._run(builder, {"operation": "get_asset", "asset_id": asset_id})
        return rows[0] if rows else None

    def create_asset(self, data: dict[str, Any]) -> dict[str, Any]:
        builder = self.client.table("assets").insert(data)
        rows = self._run(builder, {"operation": "create_asset"})
        return rows[0]

    def update_asset(self, asset_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        clean_data = {key: value for key, value in data.items() if value is not None}
        builder = self.client.table("assets").update(clean_data).eq("id", asset_id)
        rows = self._run(builder, {"operation": "update_asset", "asset_id": asset_id})
        return rows[0] if rows else None

    def delete_asset(self, asset_id: str) -> bool:
        builder = self.client.table("assets").delete().eq("id", asset_id)
        rows = self._run(builder, {"operation": "delete_asset", "asset_id": asset_id})
        return bool(rows)

    def get_asset_by_external_key(
        self,
        provider: str,
        account_id: str,
        asset_key: str,
    ) -> dict[str, Any] | None:
        builder = (
            self.client.table("assets")
            .select("*")
            .eq("external_provider", provider)
            .eq("external_account_id", account_id)
            .eq("external_asset_key", asset_key)
            .limit(1)
        )
        rows = self._run(
            builder,
            {
                "operation": "get_asset_by_external_key",
                "provider": provider,
                "account_id": account_id,
                "asset_key": asset_key,
            },
        )
        return rows[0] if rows else None

    def upsert_external_asset(self, data: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_asset_by_external_key(
            str(data.get("external_provider") or ""),
            str(data.get("external_account_id") or ""),
            str(data.get("external_asset_key") or ""),
        )
        if existing:
            updated = self.update_asset(existing["id"], data)
            return updated or existing
        return self.create_asset(data)

    def list_candidate_assets(self) -> list[dict[str, Any]]:
        builder = self.client.table("candidate_assets").select("*").order("created_at")
        return self._run(builder, {"operation": "list_candidate_assets"})

    def get_candidate_asset(self, candidate_id: str) -> dict[str, Any] | None:
        builder = self.client.table("candidate_assets").select("*").eq("id", candidate_id).limit(1)
        rows = self._run(
            builder,
            {"operation": "get_candidate_asset", "candidate_id": candidate_id},
        )
        return rows[0] if rows else None

    def create_candidate_asset(self, data: dict[str, Any]) -> dict[str, Any]:
        builder = self.client.table("candidate_assets").insert(data)
        rows = self._run(builder, {"operation": "create_candidate_asset"})
        return rows[0]

    def update_candidate_asset(
        self, candidate_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        clean_data = {key: value for key, value in data.items() if value is not None}
        builder = self.client.table("candidate_assets").update(clean_data).eq("id", candidate_id)
        rows = self._run(
            builder,
            {"operation": "update_candidate_asset", "candidate_id": candidate_id},
        )
        return rows[0] if rows else None

    def delete_candidate_asset(self, candidate_id: str) -> bool:
        builder = self.client.table("candidate_assets").delete().eq("id", candidate_id)
        rows = self._run(
            builder,
            {"operation": "delete_candidate_asset", "candidate_id": candidate_id},
        )
        return bool(rows)

    def list_candidate_universe(self, report_type: str | None = None) -> list[dict[str, Any]]:
        builder = (
            self.client.table("candidate_universe")
            .select("*")
            .eq("is_active", True)
            .order("source_rank")
            .order("ticker")
        )
        if report_type is not None:
            builder = builder.eq("report_type", report_type)
        return self._run(
            builder,
            {"operation": "list_candidate_universe", "report_type": report_type},
        )

    def upsert_candidate_universe(self, data: dict[str, Any]) -> dict[str, Any]:
        builder = self.client.table("candidate_universe").upsert(
            data,
            on_conflict="market,ticker",
        )
        rows = self._run(builder, {"operation": "upsert_candidate_universe"})
        return rows[0]

    def get_settings(self) -> dict[str, Any] | None:
        builder = self.client.table("settings").select("*").limit(1)
        rows = self._run(builder, {"operation": "get_settings"})
        return rows[0] if rows else None

    def upsert_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_settings()
        if existing:
            builder = self.client.table("settings").update(data).eq("id", existing["id"])
        else:
            builder = self.client.table("settings").insert(data)
        rows = self._run(builder, {"operation": "upsert_settings"})
        return rows[0]

    def list_reports(self) -> list[dict[str, Any]]:
        builder = self.client.table("reports").select("*").order("created_at", desc=True)
        return self._run(builder, {"operation": "list_reports"})

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        builder = self.client.table("reports").select("*").eq("id", report_id).limit(1)
        rows = self._run(builder, {"operation": "get_report", "report_id": report_id})
        return rows[0] if rows else None

    def get_latest_report(self, report_type: str | None = None) -> dict[str, Any] | None:
        builder = self.client.table("reports").select("*").order("created_at", desc=True)
        if report_type is not None:
            builder = builder.eq("report_type", report_type)
        rows = self._run(builder.limit(1), {"operation": "get_latest_report"})
        return rows[0] if rows else None

    def create_report(self, data: dict[str, Any]) -> dict[str, Any]:
        builder = self.client.table("reports").insert(data)
        rows = self._run(builder, {"operation": "create_report"})
        return rows[0]

    def create_strategy(self, data: dict[str, Any]) -> dict[str, Any]:
        builder = self.client.table("strategies").insert(data)
        rows = self._run(builder, {"operation": "create_strategy"})
        return rows[0]

    def list_strategies(self, report_id: str | None = None) -> list[dict[str, Any]]:
        builder = self.client.table("strategies").select("*").order("created_at", desc=True)
        if report_id is not None:
            builder = builder.eq("report_id", report_id)
        return self._run(builder, {"operation": "list_strategies", "report_id": report_id})

    def create_performance_log(self, data: dict[str, Any]) -> dict[str, Any]:
        builder = self.client.table("performance_logs").insert(data)
        rows = self._run(builder, {"operation": "create_performance_log"})
        return rows[0]

    def list_performance_logs(self, limit: int | None = None) -> list[dict[str, Any]]:
        builder = self.client.table("performance_logs").select("*").order("created_at", desc=True)
        if limit is not None:
            builder = builder.limit(limit)
        return self._run(builder, {"operation": "list_performance_logs"})

    def list_unevaluated_performance_logs(self, limit: int | None = None) -> list[dict[str, Any]]:
        builder = (
            self.client.table("performance_logs")
            .select("*")
            .is_("price_after_20d", "null")
            .order("created_at", desc=True)
        )
        if limit is not None:
            builder = builder.limit(limit)
        return self._run(builder, {"operation": "list_unevaluated_performance_logs"})

    def update_performance_log(self, log_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        builder = self.client.table("performance_logs").update(data).eq("id", log_id)
        rows = self._run(builder, {"operation": "update_performance_log", "log_id": log_id})
        return rows[0] if rows else None

    def create_report_job(self, data: dict[str, Any]) -> dict[str, Any]:
        builder = self.client.table("report_jobs").insert(data)
        rows = self._run(builder, {"operation": "create_report_job"})
        return rows[0]

    def update_report_job(self, job_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        clean_data = {key: value for key, value in data.items() if value is not None}
        builder = self.client.table("report_jobs").update(clean_data).eq("job_id", job_id)
        rows = self._run(builder, {"operation": "update_report_job", "job_id": job_id})
        return rows[0] if rows else None

    def get_report_job(self, job_id: str) -> dict[str, Any] | None:
        builder = self.client.table("report_jobs").select("*").eq("job_id", job_id).limit(1)
        rows = self._run(builder, {"operation": "get_report_job", "job_id": job_id})
        return rows[0] if rows else None

    def list_report_jobs(
        self, status: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        builder = self.client.table("report_jobs").select("*").order("created_at", desc=True)
        if status is not None:
            builder = builder.eq("status", status)
        if limit is not None:
            builder = builder.limit(limit)
        return self._run(builder, {"operation": "list_report_jobs", "status": status})

    def create_portfolio_snapshot(self, data: dict[str, Any]) -> dict[str, Any]:
        builder = self.client.table("portfolio_snapshots").insert(data)
        rows = self._run(builder, {"operation": "create_portfolio_snapshot"})
        return rows[0]

    def list_portfolio_snapshots(self, limit: int | None = None) -> list[dict[str, Any]]:
        builder = (
            self.client.table("portfolio_snapshots").select("*").order("created_at", desc=True)
        )
        if limit is not None:
            builder = builder.limit(limit)
        return self._run(builder, {"operation": "list_portfolio_snapshots"})

    def create_recommendation_cycle(self, data: dict[str, Any]) -> dict[str, Any]:
        builder = self.client.table("recommendation_cycles").insert(data)
        rows = self._run(builder, {"operation": "create_recommendation_cycle"})
        return rows[0]

    def update_recommendation_cycle(
        self, cycle_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        clean_data = {key: value for key, value in data.items() if value is not None}
        builder = self.client.table("recommendation_cycles").update(clean_data).eq("id", cycle_id)
        rows = self._run(
            builder, {"operation": "update_recommendation_cycle", "cycle_id": cycle_id}
        )
        return rows[0] if rows else None

    def list_recommendation_cycles(
        self, status: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        builder = (
            self.client.table("recommendation_cycles").select("*").order("created_at", desc=True)
        )
        if status is not None:
            builder = builder.eq("status", status)
        if limit is not None:
            builder = builder.limit(limit)
        return self._run(builder, {"operation": "list_recommendation_cycles", "status": status})

    def list_open_recommendation_cycles(self, limit: int | None = None) -> list[dict[str, Any]]:
        builder = (
            self.client.table("recommendation_cycles")
            .select("*")
            .or_("status.eq.active,price_after_60d.is.null")
            .order("created_at", desc=True)
        )
        if limit is not None:
            builder = builder.limit(limit)
        return self._run(builder, {"operation": "list_open_recommendation_cycles"})

    def get_market_data_cache(self, cache_key: str) -> dict[str, Any] | None:
        builder = (
            self.client.table("market_data_cache").select("*").eq("cache_key", cache_key).limit(1)
        )
        rows = self._run(builder, {"operation": "get_market_data_cache"})
        return rows[0] if rows else None

    def upsert_market_data_cache(self, cache_key: str, payload: dict[str, Any]) -> None:
        builder = self.client.table("market_data_cache").upsert(
            {"cache_key": cache_key, "payload": payload},
            on_conflict="cache_key",
        )
        self._run(builder, {"operation": "upsert_market_data_cache"})

    def list_notifications(
        self, unread_only: bool = False, limit: int | None = None
    ) -> list[dict[str, Any]]:
        builder = self.client.table("notifications").select("*").order("created_at", desc=True)
        if unread_only:
            builder = builder.eq("is_read", False)
        if limit is not None:
            builder = builder.limit(limit)
        return self._run(builder, {"operation": "list_notifications", "unread_only": unread_only})

    def get_notification_by_event_key(self, event_key: str) -> dict[str, Any] | None:
        builder = self.client.table("notifications").select("*").eq("event_key", event_key).limit(1)
        rows = self._run(builder, {"operation": "get_notification_by_event_key"})
        return rows[0] if rows else None

    def create_notification(self, data: dict[str, Any]) -> dict[str, Any]:
        builder = self.client.table("notifications").insert(data)
        rows = self._run(builder, {"operation": "create_notification"})
        return rows[0]

    def update_notification(
        self, notification_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        builder = self.client.table("notifications").update(data).eq("id", notification_id)
        rows = self._run(builder, {"operation": "update_notification"})
        return rows[0] if rows else None

    def mark_all_notifications_read(self) -> int:
        builder = (
            self.client.table("notifications")
            .update({"is_read": True, "read_at": _now_iso()})
            .eq("is_read", False)
        )
        return len(self._run(builder, {"operation": "mark_all_notifications_read"}))


def create_repository(env: EnvironmentSettings | None = None) -> Repository:
    current_env = env or get_environment_settings()
    if is_supabase_configured(current_env):
        return SupabaseRepository(current_env)
    log_external_failure(
        "supabase",
        RuntimeError("Supabase is not configured; using local in-memory repository"),
        {"operation": "create_repository", "app_env": current_env.app_env},
    )
    return InMemoryRepository()
