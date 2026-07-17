from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from json import dumps
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4

from httpx import TransportError
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

    def create_advisory_job(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def update_advisory_job(self, job_id: str, data: dict[str, Any]) -> dict[str, Any] | None: ...

    def get_advisory_job(self, job_id: str) -> dict[str, Any] | None: ...

    def list_advisory_jobs(self, limit: int | None = None) -> list[dict[str, Any]]: ...

    def create_advisory_analysis(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def get_advisory_analysis(self, analysis_id: str) -> dict[str, Any] | None: ...

    def list_advisory_analyses(
        self, analysis_type: str | None = None, limit: int | None = None
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

    def list_signal_model_versions(self) -> list[dict[str, Any]]: ...

    def create_signal_model_version(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def list_signal_model_assignments(self) -> list[dict[str, Any]]: ...

    def create_signal_model_assignment(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def list_signal_model_evaluation_runs(self) -> list[dict[str, Any]]: ...

    def create_signal_model_evaluation_run(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def list_signal_model_evaluation_observations(self) -> list[dict[str, Any]]: ...

    def create_signal_model_evaluation_observation(
        self, data: dict[str, Any]
    ) -> dict[str, Any]: ...

    def list_signal_model_report_links(self) -> list[dict[str, Any]]: ...

    def create_signal_model_report_link(self, data: dict[str, Any]) -> dict[str, Any]: ...


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _copy_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [deepcopy(row) for row in rows]


def _prepare_signal_model_version(data: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(data)
    config = row.get("config")
    if not isinstance(config, Mapping):
        raise ValueError("signal model version config must be an object")
    try:
        config_sha256 = sha256(
            dumps(dict(config), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    except (TypeError, ValueError) as exc:
        raise ValueError("signal model version config must be JSON serializable") from exc
    provided_sha256 = row.get("config_sha256")
    if provided_sha256 is not None and provided_sha256 != config_sha256:
        raise ValueError("signal model version config_sha256 does not match config")
    row["config"] = dict(config)
    row["config_sha256"] = config_sha256
    row["metadata"] = row.get("metadata") or {
        "research_only": True,
        "adoption_permitted": False,
        "promotion_mode": "manual_only",
        "evaluation_window_weeks": 12,
    }
    return row


def _canonical_json_sha256(value: Mapping[str, Any]) -> str:
    try:
        payload = dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("signal model snapshot must be JSON serializable") from exc
    return sha256(payload.encode()).hexdigest()


def _twelve_week_end(started_at: str) -> str:
    try:
        parsed = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("evaluation started_at must be an ISO datetime") from exc
    return (parsed + timedelta(weeks=12)).isoformat()


def _prepare_signal_model_evaluation_run(
    data: dict[str, Any],
    versions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    row = deepcopy(data)
    champion_model_version_id = str(row.get("champion_model_version_id") or "")
    challenger_model_version_id = str(row.get("challenger_model_version_id") or "")
    if (
        champion_model_version_id not in versions
        or challenger_model_version_id not in versions
        or champion_model_version_id == challenger_model_version_id
    ):
        raise ValueError("evaluation run requires distinct known champion and challenger versions")
    if row.get("evaluation_window_weeks", 12) != 12:
        raise ValueError("evaluation_window_weeks is fixed at 12")
    if row.get("trigger_type") != "scheduled":
        raise ValueError("evaluation run trigger_type must be scheduled")
    if not row.get("report_type") or not row.get("decision_at"):
        raise ValueError("evaluation run requires report_type and decision_at")
    input_snapshot = row.get("input_snapshot")
    if not isinstance(input_snapshot, Mapping):
        raise ValueError("evaluation run input_snapshot must be an object")

    now = _now_iso()
    started_at = row.get("started_at") or now
    ends_at = _twelve_week_end(started_at)
    if row.get("ends_at") is not None and row["ends_at"] != ends_at:
        raise ValueError("evaluation run ends_at must equal started_at plus 12 weeks")
    champion_sha256 = str(versions[champion_model_version_id].get("config_sha256") or "")
    challenger_sha256 = str(versions[challenger_model_version_id].get("config_sha256") or "")
    if row.get("champion_config_sha256") not in {None, champion_sha256}:
        raise ValueError("evaluation run champion config hash does not match its model version")
    if row.get("challenger_config_sha256") not in {None, challenger_sha256}:
        raise ValueError("evaluation run challenger config hash does not match its model version")
    input_sha256 = _canonical_json_sha256(input_snapshot)
    if row.get("input_sha256") not in {None, input_sha256}:
        raise ValueError("evaluation run input hash does not match input_snapshot")

    status = row.get("status") or "pending"
    if status not in {"pending", "collecting", "review_ready", "failed"}:
        raise ValueError("evaluation run status is invalid")
    if (status == "failed") != bool(row.get("failure_reason")):
        raise ValueError("failed evaluations require failure_reason and other states must omit it")
    completed_at = row.get("completed_at")
    if status == "review_ready":
        if completed_at is None:
            raise ValueError("review-ready evaluations require completed_at")
        try:
            completed = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
            ends = datetime.fromisoformat(ends_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("evaluation completed_at must be an ISO datetime") from exc
        if completed.tzinfo is None or ends.tzinfo is None:
            raise ValueError("evaluation timestamps must include a timezone")
        if completed < ends:
            raise ValueError("review-ready evaluations must complete after the 12-week window")
        if ends.tzinfo is None or datetime.now(timezone.utc) < ends:
            raise ValueError("review-ready evaluations must wait for the 12-week window")
    for field in (
        "expected_observation_count",
        "observed_observation_count",
        "excluded_observation_count",
    ):
        if int(row.get(field) or 0) < 0:
            raise ValueError(f"{field} must not be negative")

    row["champion_model_version_id"] = champion_model_version_id
    row["challenger_model_version_id"] = challenger_model_version_id
    row["champion_config_sha256"] = champion_sha256
    row["challenger_config_sha256"] = challenger_sha256
    row["evaluation_window_weeks"] = 12
    row["started_at"] = started_at
    row["ends_at"] = ends_at
    row["status"] = status
    row["expected_observation_count"] = int(row.get("expected_observation_count") or 0)
    row["observed_observation_count"] = int(row.get("observed_observation_count") or 0)
    row["excluded_observation_count"] = int(row.get("excluded_observation_count") or 0)
    row["input_snapshot"] = dict(input_snapshot)
    row["input_sha256"] = input_sha256
    return row


def _prepare_signal_model_report_link(data: dict[str, Any]) -> dict[str, Any]:
    row = deepcopy(data)
    snapshot = row.get("report_inputs_snapshot")
    if not isinstance(snapshot, Mapping):
        raise ValueError("signal model report link requires report_inputs_snapshot")
    input_sha256 = _canonical_json_sha256(snapshot)
    if row.get("input_sha256") not in {None, input_sha256}:
        raise ValueError("signal model report link input hash does not match snapshot")
    row["report_inputs_snapshot"] = dict(snapshot)
    row["input_sha256"] = input_sha256
    return row


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
        self.advisory_jobs: dict[str, dict[str, Any]] = {}
        self.advisory_analyses: dict[str, dict[str, Any]] = {}
        self.portfolio_snapshots: dict[str, dict[str, Any]] = {}
        self.recommendation_cycles: dict[str, dict[str, Any]] = {}
        self.market_data_cache: dict[str, dict[str, Any]] = {}
        self.notifications: dict[str, dict[str, Any]] = {}
        self.signal_model_versions: dict[str, dict[str, Any]] = {}
        self.signal_model_assignments: dict[str, dict[str, Any]] = {}
        self.signal_model_evaluation_runs: dict[str, dict[str, Any]] = {}
        self.signal_model_evaluation_observations: dict[str, dict[str, Any]] = {}
        self.signal_model_report_links: dict[str, dict[str, Any]] = {}

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

    def create_advisory_job(self, data: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(data)
        row["job_id"] = row.get("job_id") or str(uuid4())
        now = _now_iso()
        row["created_at"] = row.get("created_at") or now
        row["updated_at"] = row.get("updated_at") or now
        row["step_timings"] = row.get("step_timings") or {}
        self.advisory_jobs[row["job_id"]] = row
        return deepcopy(row)

    def update_advisory_job(self, job_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        if job_id not in self.advisory_jobs:
            return None
        self.advisory_jobs[job_id].update(
            {key: value for key, value in data.items() if value is not None}
        )
        self.advisory_jobs[job_id]["updated_at"] = _now_iso()
        return deepcopy(self.advisory_jobs[job_id])

    def get_advisory_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.advisory_jobs.get(job_id)
        return deepcopy(row) if row else None

    def list_advisory_jobs(self, limit: int | None = None) -> list[dict[str, Any]]:
        rows = sorted(
            _copy_rows(self.advisory_jobs.values()),
            key=lambda row: row.get("created_at") or "",
            reverse=True,
        )
        return rows[:limit] if limit is not None else rows

    def create_advisory_analysis(self, data: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(data)
        row["analysis_id"] = row.get("analysis_id") or str(uuid4())
        row["created_at"] = row.get("created_at") or _now_iso()
        self.advisory_analyses[row["analysis_id"]] = row
        return deepcopy(row)

    def get_advisory_analysis(self, analysis_id: str) -> dict[str, Any] | None:
        row = self.advisory_analyses.get(analysis_id)
        return deepcopy(row) if row else None

    def list_advisory_analyses(
        self, analysis_type: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        rows = _copy_rows(self.advisory_analyses.values())
        if analysis_type is not None:
            rows = [row for row in rows if row.get("analysis_type") == analysis_type]
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
        self.recommendation_cycles[cycle_id].update(data)
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

    def list_signal_model_versions(self) -> list[dict[str, Any]]:
        return sorted(
            _copy_rows(self.signal_model_versions.values()),
            key=lambda row: (row.get("model_key") or "", row.get("version") or ""),
        )

    def create_signal_model_version(self, data: dict[str, Any]) -> dict[str, Any]:
        row = _prepare_signal_model_version(data)
        if not row.get("model_key") or not row.get("version"):
            raise ValueError("signal model version requires model_key and version")
        if any(
            existing.get("model_key") == row["model_key"]
            and existing.get("version") == row["version"]
            for existing in self.signal_model_versions.values()
        ):
            raise ValueError("signal model version already exists")
        if any(
            existing.get("config_sha256") == row["config_sha256"]
            for existing in self.signal_model_versions.values()
        ):
            raise ValueError("signal model configuration already exists")
        row["id"] = row.get("id") or str(uuid4())
        row["created_at"] = row.get("created_at") or _now_iso()
        self.signal_model_versions[row["id"]] = row
        return deepcopy(row)

    def list_signal_model_assignments(self) -> list[dict[str, Any]]:
        return sorted(
            _copy_rows(self.signal_model_assignments.values()),
            key=lambda row: row.get("effective_at") or row.get("created_at") or "",
            reverse=True,
        )

    def create_signal_model_assignment(self, data: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(data)
        model_version_id = str(row.get("model_version_id") or "")
        role = row.get("role")
        if model_version_id not in self.signal_model_versions:
            raise ValueError("signal model assignment references an unknown model version")
        if role not in {"champion", "challenger"}:
            raise ValueError("signal model assignment role must be champion or challenger")
        if row.get("ended_at") is None and any(
            existing.get("role") == role and existing.get("ended_at") is None
            for existing in self.signal_model_assignments.values()
        ):
            raise ValueError("an active assignment already exists for this role")
        now = _now_iso()
        row["id"] = row.get("id") or str(uuid4())
        row["model_version_id"] = model_version_id
        row["effective_at"] = row.get("effective_at") or now
        row["assignment_reason"] = row.get("assignment_reason") or "manual_review"
        row["metadata"] = row.get("metadata") or {
            "research_only": True,
            "promotion_mode": "manual_only",
        }
        row["created_at"] = row.get("created_at") or now
        self.signal_model_assignments[row["id"]] = row
        return deepcopy(row)

    def list_signal_model_evaluation_runs(self) -> list[dict[str, Any]]:
        return sorted(
            _copy_rows(self.signal_model_evaluation_runs.values()),
            key=lambda row: row.get("created_at") or "",
            reverse=True,
        )

    def create_signal_model_evaluation_run(self, data: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(data)
        champion_model_version_id = str(row.get("champion_model_version_id") or "")
        challenger_model_version_id = str(row.get("challenger_model_version_id") or "")
        if (
            champion_model_version_id not in self.signal_model_versions
            or challenger_model_version_id not in self.signal_model_versions
            or champion_model_version_id == challenger_model_version_id
        ):
            raise ValueError(
                "evaluation run requires distinct known champion and challenger versions"
            )
        if row.get("evaluation_window_weeks", 12) != 12:
            raise ValueError("evaluation_window_weeks is fixed at 12")
        if row.get("trigger_type") != "scheduled":
            raise ValueError("evaluation run trigger_type must be scheduled")
        if not row.get("report_type") or not row.get("decision_at"):
            raise ValueError("evaluation run requires report_type and decision_at")
        input_snapshot = row.get("input_snapshot")
        if not isinstance(input_snapshot, Mapping):
            raise ValueError("evaluation run input_snapshot must be an object")
        now = _now_iso()
        started_at = row.get("started_at") or now
        ends_at = _twelve_week_end(started_at)
        if row.get("ends_at") is not None and row["ends_at"] != ends_at:
            raise ValueError("evaluation run ends_at must equal started_at plus 12 weeks")
        champion_sha256 = self.signal_model_versions[champion_model_version_id]["config_sha256"]
        challenger_sha256 = self.signal_model_versions[challenger_model_version_id]["config_sha256"]
        if row.get("champion_config_sha256") not in {None, champion_sha256}:
            raise ValueError("evaluation run champion config hash does not match its model version")
        if row.get("challenger_config_sha256") not in {None, challenger_sha256}:
            raise ValueError(
                "evaluation run challenger config hash does not match its model version"
            )
        input_sha256 = _canonical_json_sha256(input_snapshot)
        if row.get("input_sha256") not in {None, input_sha256}:
            raise ValueError("evaluation run input hash does not match input_snapshot")
        status = row.get("status") or "pending"
        if status not in {"pending", "collecting", "review_ready", "failed"}:
            raise ValueError("evaluation run status is invalid")
        if (status == "failed") != bool(row.get("failure_reason")):
            raise ValueError(
                "failed evaluations require failure_reason and other states must omit it"
            )
        if status == "review_ready":
            completed_at = row.get("completed_at")
            if completed_at is None:
                raise ValueError("review-ready evaluations require completed_at")
            try:
                completed = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
                ends = datetime.fromisoformat(ends_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("evaluation completed_at must be an ISO datetime") from exc
            if completed.tzinfo is None or ends.tzinfo is None:
                raise ValueError("evaluation timestamps must include a timezone")
            if completed < ends:
                raise ValueError("review-ready evaluations must complete after the 12-week window")
            if ends.tzinfo is None or datetime.now(timezone.utc) < ends:
                raise ValueError("review-ready evaluations must wait for the 12-week window")
        for field in (
            "expected_observation_count",
            "observed_observation_count",
            "excluded_observation_count",
        ):
            if int(row.get(field) or 0) < 0:
                raise ValueError(f"{field} must not be negative")
        row["id"] = row.get("id") or str(uuid4())
        row["champion_model_version_id"] = champion_model_version_id
        row["challenger_model_version_id"] = challenger_model_version_id
        row["champion_config_sha256"] = champion_sha256
        row["challenger_config_sha256"] = challenger_sha256
        row["evaluation_window_weeks"] = 12
        row["started_at"] = started_at
        row["ends_at"] = ends_at
        row["status"] = status
        row["expected_observation_count"] = int(row.get("expected_observation_count") or 0)
        row["observed_observation_count"] = int(row.get("observed_observation_count") or 0)
        row["excluded_observation_count"] = int(row.get("excluded_observation_count") or 0)
        row["input_snapshot"] = dict(input_snapshot)
        row["input_sha256"] = input_sha256
        row["created_at"] = row.get("created_at") or now
        self.signal_model_evaluation_runs[row["id"]] = row
        return deepcopy(row)

    def list_signal_model_evaluation_observations(self) -> list[dict[str, Any]]:
        return sorted(
            _copy_rows(self.signal_model_evaluation_observations.values()),
            key=lambda row: row.get("observed_at") or "",
        )

    def create_signal_model_evaluation_observation(self, data: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(data)
        run_id = str(row.get("evaluation_run_id") or "")
        run = self.signal_model_evaluation_runs.get(run_id)
        arm = row.get("arm")
        if run is None or arm not in {"champion", "challenger"}:
            raise ValueError("evaluation observation requires a known run and arm")
        expected_model_version_id = str(run[f"{arm}_model_version_id"])
        if str(row.get("model_version_id") or "") != expected_model_version_id:
            raise ValueError("evaluation observation model version does not match its arm")
        required_fields = (
            "observation_key",
            "observed_at",
            "market",
            "ticker",
            "action",
            "horizon",
        )
        if any(not row.get(field) for field in required_fields):
            raise ValueError("evaluation observation is missing required audit fields")
        returns = row.get("returns") or {}
        outcome_snapshot = row.get("outcome_snapshot") or {}
        if not isinstance(returns, Mapping) or not isinstance(outcome_snapshot, Mapping):
            raise ValueError("evaluation observation returns and outcome_snapshot must be objects")
        if any(
            existing.get("evaluation_run_id") == run_id
            and existing.get("arm") == arm
            and existing.get("observation_key") == row["observation_key"]
            for existing in self.signal_model_evaluation_observations.values()
        ):
            raise ValueError("evaluation observation already exists for this arm and key")
        row["id"] = row.get("id") or str(uuid4())
        row["evaluation_run_id"] = run_id
        row["model_version_id"] = expected_model_version_id
        row["outcome_status"] = row.get("outcome_status") or "pending"
        row["returns"] = dict(returns)
        row["outcome_snapshot"] = dict(outcome_snapshot)
        row["created_at"] = row.get("created_at") or _now_iso()
        self.signal_model_evaluation_observations[row["id"]] = row
        return deepcopy(row)

    def list_signal_model_report_links(self) -> list[dict[str, Any]]:
        return sorted(
            _copy_rows(self.signal_model_report_links.values()),
            key=lambda row: row.get("created_at") or "",
            reverse=True,
        )

    def create_signal_model_report_link(self, data: dict[str, Any]) -> dict[str, Any]:
        row = _prepare_signal_model_report_link(data)
        report_id = str(row.get("report_id") or "")
        champion_assignment_id = str(row.get("champion_assignment_id") or "")
        champion_version_id = str(row.get("champion_version_id") or "")
        generation_source = row.get("generation_source")
        if report_id not in self.reports:
            raise ValueError("signal model report link references an unknown report")
        if champion_version_id not in self.signal_model_versions:
            raise ValueError("signal model report link references an unknown champion version")
        champion_assignment = self.signal_model_assignments.get(champion_assignment_id)
        if (
            champion_assignment is None
            or champion_assignment.get("role") != "champion"
            or str(champion_assignment.get("model_version_id")) != champion_version_id
            or champion_assignment.get("ended_at") is not None
        ):
            raise ValueError(
                "signal model report link champion assignment does not match its model version"
            )
        if generation_source not in {"scheduled", "manual"}:
            raise ValueError("signal model report link generation_source is invalid")
        if row.get("is_official_sample") is not (generation_source == "scheduled"):
            raise ValueError("scheduled report links must be official and manual links must not")
        if generation_source == "manual" and row.get("evaluation_id") is not None:
            raise ValueError("manual report links must not reference an evaluation")
        if report_id in self.signal_model_report_links:
            raise ValueError("signal model report link already exists for this report")
        now = _now_iso()
        row["report_id"] = report_id
        row["champion_assignment_id"] = champion_assignment_id
        row["champion_version_id"] = champion_version_id
        row["created_at"] = row.get("created_at") or now
        row["updated_at"] = row.get("updated_at") or now
        self.signal_model_report_links[report_id] = row
        return deepcopy(row)


class SupabaseRepository:
    def __init__(self, env: EnvironmentSettings | None = None, client: Any | None = None) -> None:
        current_env = env or get_environment_settings()
        if client is None:
            from supabase import create_client

            if not current_env.supabase_url or not current_env.supabase_service_role_key:
                raise RuntimeError("Supabase configuration is missing")
            client = create_client(current_env.supabase_url, current_env.supabase_service_role_key)
        self.client = client
        self._execute_lock = RLock()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, TransportError)),
        reraise=True,
    )
    def _execute(self, builder: Any) -> Any:
        # The sync Supabase client owns one HTTP connection pool. FastAPI runs sync
        # endpoints in worker threads, so concurrent use can corrupt an HTTP/2 stream.
        with self._execute_lock:
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

    def create_advisory_job(self, data: dict[str, Any]) -> dict[str, Any]:
        builder = self.client.table("advisory_jobs").insert(data)
        rows = self._run(builder, {"operation": "create_advisory_job"})
        return rows[0]

    def update_advisory_job(self, job_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        clean_data = {key: value for key, value in data.items() if value is not None}
        builder = self.client.table("advisory_jobs").update(clean_data).eq("job_id", job_id)
        rows = self._run(builder, {"operation": "update_advisory_job", "job_id": job_id})
        return rows[0] if rows else None

    def get_advisory_job(self, job_id: str) -> dict[str, Any] | None:
        builder = self.client.table("advisory_jobs").select("*").eq("job_id", job_id).limit(1)
        rows = self._run(builder, {"operation": "get_advisory_job", "job_id": job_id})
        return rows[0] if rows else None

    def list_advisory_jobs(self, limit: int | None = None) -> list[dict[str, Any]]:
        builder = self.client.table("advisory_jobs").select("*").order("created_at", desc=True)
        if limit is not None:
            builder = builder.limit(limit)
        return self._run(builder, {"operation": "list_advisory_jobs"})

    def create_advisory_analysis(self, data: dict[str, Any]) -> dict[str, Any]:
        builder = self.client.table("advisory_analyses").insert(data)
        rows = self._run(builder, {"operation": "create_advisory_analysis"})
        return rows[0]

    def get_advisory_analysis(self, analysis_id: str) -> dict[str, Any] | None:
        builder = (
            self.client.table("advisory_analyses")
            .select("*")
            .eq("analysis_id", analysis_id)
            .limit(1)
        )
        rows = self._run(
            builder,
            {"operation": "get_advisory_analysis", "analysis_id": analysis_id},
        )
        return rows[0] if rows else None

    def list_advisory_analyses(
        self, analysis_type: str | None = None, limit: int | None = None
    ) -> list[dict[str, Any]]:
        builder = self.client.table("advisory_analyses").select("*").order("created_at", desc=True)
        if analysis_type is not None:
            builder = builder.eq("analysis_type", analysis_type)
        if limit is not None:
            builder = builder.limit(limit)
        return self._run(
            builder,
            {"operation": "list_advisory_analyses", "analysis_type": analysis_type},
        )

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
        builder = self.client.table("recommendation_cycles").update(data).eq("id", cycle_id)
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

    def list_signal_model_versions(self) -> list[dict[str, Any]]:
        builder = self.client.table("signal_model_versions").select("*").order("created_at")
        return self._run(builder, {"operation": "list_signal_model_versions"})

    def create_signal_model_version(self, data: dict[str, Any]) -> dict[str, Any]:
        builder = self.client.table("signal_model_versions").insert(
            _prepare_signal_model_version(data)
        )
        rows = self._run(builder, {"operation": "create_signal_model_version"})
        return rows[0]

    def list_signal_model_assignments(self) -> list[dict[str, Any]]:
        builder = (
            self.client.table("signal_model_assignments")
            .select("*")
            .order("effective_at", desc=True)
        )
        return self._run(builder, {"operation": "list_signal_model_assignments"})

    def create_signal_model_assignment(self, data: dict[str, Any]) -> dict[str, Any]:
        builder = self.client.table("signal_model_assignments").insert(data)
        rows = self._run(builder, {"operation": "create_signal_model_assignment"})
        return rows[0]

    def list_signal_model_evaluation_runs(self) -> list[dict[str, Any]]:
        builder = (
            self.client.table("signal_model_evaluation_runs")
            .select("*")
            .order("created_at", desc=True)
        )
        return self._run(builder, {"operation": "list_signal_model_evaluation_runs"})

    def create_signal_model_evaluation_run(self, data: dict[str, Any]) -> dict[str, Any]:
        versions = {
            str(row["id"]): row
            for row in self.list_signal_model_versions()
            if row.get("id") is not None
        }
        builder = self.client.table("signal_model_evaluation_runs").insert(
            _prepare_signal_model_evaluation_run(data, versions)
        )
        rows = self._run(builder, {"operation": "create_signal_model_evaluation_run"})
        return rows[0]

    def list_signal_model_evaluation_observations(self) -> list[dict[str, Any]]:
        builder = (
            self.client.table("signal_model_evaluation_observations")
            .select("*")
            .order("observed_at")
        )
        return self._run(builder, {"operation": "list_signal_model_evaluation_observations"})

    def create_signal_model_evaluation_observation(self, data: dict[str, Any]) -> dict[str, Any]:
        builder = self.client.table("signal_model_evaluation_observations").insert(data)
        rows = self._run(builder, {"operation": "create_signal_model_evaluation_observation"})
        return rows[0]

    def list_signal_model_report_links(self) -> list[dict[str, Any]]:
        builder = (
            self.client.table("signal_model_report_links")
            .select("*")
            .order("created_at", desc=True)
        )
        return self._run(builder, {"operation": "list_signal_model_report_links"})

    def create_signal_model_report_link(self, data: dict[str, Any]) -> dict[str, Any]:
        builder = self.client.table("signal_model_report_links").insert(
            _prepare_signal_model_report_link(data)
        )
        rows = self._run(builder, {"operation": "create_signal_model_report_link"})
        return rows[0]


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
