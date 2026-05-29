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

    def list_candidate_assets(self) -> list[dict[str, Any]]: ...

    def get_candidate_asset(self, candidate_id: str) -> dict[str, Any] | None: ...

    def create_candidate_asset(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def update_candidate_asset(
        self, candidate_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None: ...

    def delete_candidate_asset(self, candidate_id: str) -> bool: ...

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

    def update_performance_log(
        self, log_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None: ...


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _copy_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [deepcopy(row) for row in rows]


class InMemoryRepository:
    def __init__(self) -> None:
        self.assets: dict[str, dict[str, Any]] = {}
        self.candidate_assets: dict[str, dict[str, Any]] = {}
        self.settings: dict[str, Any] | None = None
        self.reports: dict[str, dict[str, Any]] = {}
        self.strategies: dict[str, dict[str, Any]] = {}
        self.performance_logs: dict[str, dict[str, Any]] = {}

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

    def update_performance_log(self, log_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        if log_id not in self.performance_logs:
            return None
        self.performance_logs[log_id].update(
            {key: value for key, value in data.items() if value is not None}
        )
        return deepcopy(self.performance_logs[log_id])


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

    def update_performance_log(self, log_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        builder = self.client.table("performance_logs").update(data).eq("id", log_id)
        rows = self._run(builder, {"operation": "update_performance_log", "log_id": log_id})
        return rows[0] if rows else None


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
