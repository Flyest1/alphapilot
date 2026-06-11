"""리포트/전략/성과 로그/추천 사이클/스냅샷 저장 책임 모듈."""

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.db.supabase_client import Repository
from app.models.report import AssetStrategy, ReportContent
from app.utils.datetime import parse_iso_datetime
from app.utils.labels import report_type_label
from app.utils.logging import log_external_failure

RECOMMENDATION_PRICE_CHANGE_THRESHOLD = 0.05


class ReportPersistence:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def save_report(
        self,
        content: ReportContent,
        assets: list[dict[str, Any]],
        candidate_horizon: str,
        portfolio_summary: dict[str, Any],
        frontend_timezone: str,
        report_inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        report_data = {
            "report_type": content.report_type,
            "title": f"{report_type_label(content.report_type)} 시장 리포트",
            "summary": content.market_summary.summary,
            "content": content.model_dump(mode="json"),
        }
        if report_inputs is not None:
            report_data["report_inputs"] = report_inputs
        try:
            report = self.repository.create_report(report_data)
        except Exception:
            if "report_inputs" not in report_data:
                raise
            # 마이그레이션 010(report_inputs 컬럼) 미적용 환경에서도 리포트 저장은 계속한다.
            report_data.pop("report_inputs")
            report = self.repository.create_report(report_data)
            log_external_failure(
                "reports",
                RuntimeError("report_inputs column missing; saved report without snapshot"),
                {"operation": "create_report_without_inputs"},
            )
        assets_by_ticker = {asset["ticker"]: asset for asset in assets}
        existing_logs = self.repository.list_performance_logs(limit=500)
        existing_strategies = {row["id"]: row for row in self.repository.list_strategies()}
        existing_cycles = self.repository.list_recommendation_cycles(limit=500)
        for strategy in content.asset_strategies:
            asset = assets_by_ticker.get(strategy.ticker)
            strategy_row = self.repository.create_strategy(
                {
                    "report_id": report["id"],
                    "asset_id": asset["id"] if asset else None,
                    "ticker": strategy.ticker,
                    "name": strategy.name,
                    "action": strategy.action,
                    "confidence": strategy.confidence,
                    "current_price": strategy.current_price,
                    "buy_range_low": strategy.buy_range_low,
                    "buy_range_high": strategy.buy_range_high,
                    "sell_range_low": strategy.sell_range_low,
                    "sell_range_high": strategy.sell_range_high,
                    "target_price": strategy.target_price,
                    "stop_loss": strategy.stop_loss,
                    "reasoning": strategy.reasoning,
                    "risk": strategy.risk,
                    "invalidation_condition": strategy.invalidation_condition,
                }
            )
            if self._should_start_performance_log(strategy, existing_logs, existing_strategies):
                self.repository.create_performance_log(
                    {
                        "strategy_id": strategy_row["id"],
                        "ticker": strategy.ticker,
                        "action": strategy.action,
                        "price_at_recommendation": strategy.current_price,
                    }
                )
            self.sync_recommendation_cycle(
                strategy=strategy,
                strategy_row=strategy_row,
                report=report,
                horizon=candidate_horizon,
                existing_cycles=existing_cycles,
            )
        self.save_portfolio_snapshot(
            report=report,
            report_type=content.report_type,
            portfolio_summary=portfolio_summary,
            frontend_timezone=frontend_timezone,
        )
        return report

    def save_portfolio_snapshot(
        self,
        report: dict[str, Any],
        report_type: str,
        portfolio_summary: dict[str, Any],
        frontend_timezone: str,
    ) -> None:
        try:
            tz = ZoneInfo(frontend_timezone)
        except Exception:
            tz = timezone.utc
        try:
            self.repository.create_portfolio_snapshot(
                {
                    "report_id": report.get("id"),
                    "report_type": report_type,
                    "snapshot_date": datetime.now(tz).date().isoformat(),
                    "total_market_value": portfolio_summary.get("total_market_value") or 0,
                    "total_cost": portfolio_summary.get("total_cost") or 0,
                    "total_profit_loss": portfolio_summary.get("total_profit_loss") or 0,
                    "total_return_rate": portfolio_summary.get("total_return_rate") or 0,
                    "daily_profit_loss": portfolio_summary.get("daily_profit_loss") or 0,
                    "daily_return_rate": portfolio_summary.get("daily_return_rate") or 0,
                    "domestic_value": portfolio_summary.get("domestic_value") or 0,
                    "global_value": portfolio_summary.get("global_value") or 0,
                    "cash_value": portfolio_summary.get("cash_value") or 0,
                    "usd_krw_rate": portfolio_summary.get("usd_krw_rate") or 1400,
                    "asset_allocation": portfolio_summary.get("asset_allocation") or [],
                    "asset_returns": portfolio_summary.get("asset_returns") or [],
                }
            )
        except Exception as exc:
            log_external_failure(
                "portfolio_snapshots",
                exc,
                {"operation": "create_portfolio_snapshot", "report_id": report.get("id")},
            )

    def sync_recommendation_cycle(
        self,
        strategy: AssetStrategy,
        strategy_row: dict[str, Any],
        report: dict[str, Any],
        horizon: str,
        existing_cycles: list[dict[str, Any]],
    ) -> None:
        if strategy.current_price is None or strategy.reasoning == "data-limited":
            return
        active_cycles = [
            row
            for row in existing_cycles
            if row.get("ticker") == strategy.ticker
            and row.get("horizon") == horizon
            and row.get("status") == "active"
        ]
        reusable_cycle = next(
            (
                row
                for row in active_cycles
                if row.get("action") == strategy.action
                and not self._material_price_change(row, strategy)
            ),
            None,
        )
        now = datetime.now(timezone.utc).isoformat()
        if reusable_cycle:
            updated = self.repository.update_recommendation_cycle(
                reusable_cycle["id"],
                {
                    "strategy_id": strategy_row["id"],
                    "report_id": report["id"],
                    "target_price": strategy.target_price,
                    "stop_loss": strategy.stop_loss,
                    "metadata": {
                        **(reusable_cycle.get("metadata") or {}),
                        "last_seen_at": now,
                        "latest_confidence": strategy.confidence,
                    },
                },
            )
            if updated:
                existing_cycles[:] = [
                    updated if row.get("id") == updated.get("id") else row
                    for row in existing_cycles
                ]
            return

        for row in active_cycles:
            closed = self.repository.update_recommendation_cycle(
                row["id"],
                {
                    "status": "superseded",
                    "closed_at": now,
                    "metadata": {
                        **(row.get("metadata") or {}),
                        "superseded_by_strategy_id": strategy_row["id"],
                    },
                },
            )
            if closed:
                existing_cycles[:] = [
                    closed if item.get("id") == closed.get("id") else item
                    for item in existing_cycles
                ]

        created = self.repository.create_recommendation_cycle(
            {
                "strategy_id": strategy_row["id"],
                "report_id": report["id"],
                "report_type": report["report_type"],
                "ticker": strategy.ticker,
                "name": strategy.name,
                "action": strategy.action,
                "horizon": horizon,
                "status": "active",
                "reference_price": strategy.current_price,
                "target_price": strategy.target_price,
                "stop_loss": strategy.stop_loss,
                "metadata": {
                    "confidence": strategy.confidence,
                    "buy_range_low": strategy.buy_range_low,
                    "buy_range_high": strategy.buy_range_high,
                    "sell_range_low": strategy.sell_range_low,
                    "sell_range_high": strategy.sell_range_high,
                    "reasoning": strategy.reasoning,
                },
            }
        )
        existing_cycles.append(created)

    def _material_price_change(self, cycle: dict[str, Any], strategy: AssetStrategy) -> bool:
        return self._price_changed(cycle.get("target_price"), strategy.target_price) or (
            self._price_changed(cycle.get("stop_loss"), strategy.stop_loss)
        )

    def _price_changed(self, old_value: Any, new_value: Any) -> bool:
        if old_value is None and new_value is None:
            return False
        if old_value is None or new_value is None:
            return True
        old_float = float(old_value)
        new_float = float(new_value)
        if old_float == 0:
            return new_float != 0
        return abs(new_float - old_float) / abs(old_float) >= RECOMMENDATION_PRICE_CHANGE_THRESHOLD

    def _should_start_performance_log(
        self,
        strategy: AssetStrategy,
        existing_logs: list[dict[str, Any]],
        existing_strategies: dict[str, dict[str, Any]],
    ) -> bool:
        if strategy.current_price is None or strategy.reasoning == "data-limited":
            return False
        for log_row in existing_logs:
            if log_row.get("ticker") != strategy.ticker or log_row.get("action") != strategy.action:
                continue
            existing_strategy = existing_strategies.get(log_row.get("strategy_id"), {})
            created_at = parse_iso_datetime(
                existing_strategy.get("created_at") or log_row.get("created_at")
            )
            if created_at is None:
                return False
            age_days = (datetime.now(timezone.utc) - created_at.astimezone(timezone.utc)).days
            if age_days <= 1:
                return False
            if log_row.get("price_after_20d") is not None:
                continue
            if age_days <= 35:
                return False
        return True
