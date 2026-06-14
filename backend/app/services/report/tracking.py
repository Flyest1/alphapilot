"""performance_logs / recommendation_cycles 백필과 사이클 상태 동기화 모듈.

리포트 생성 시마다 호출되므로, 평가가 끝나지 않은 행만 조회하고
같은 티커의 가격 이력은 한 번만 조회해 재사용한다.
"""

from datetime import datetime, timezone
from typing import Any

from app.db.supabase_client import Repository
from app.services.market_data_service import MarketDataService
from app.utils.datetime import parse_iso_datetime
from app.utils.logging import log_external_failure
from app.utils.tickers import infer_market

HORIZON_DAYS = {"short": 5, "medium": 20, "long": 60}


def horizon_days(horizon: Any) -> int:
    return HORIZON_DAYS.get(str(horizon or "medium"), 20)


class PerformanceTracker:
    def __init__(self, repository: Repository, market_data_service: MarketDataService) -> None:
        self.repository = repository
        self.market_data_service = market_data_service
        self._history_cache: dict[tuple[str, str, int], Any] = {}

    def backfill_performance_logs(self) -> None:
        try:
            logs = self._unevaluated_performance_logs(limit=250)
            strategies = {row["id"]: row for row in self.repository.list_strategies()}
            for log_row in logs:
                strategy = strategies.get(log_row.get("strategy_id"))
                if not strategy:
                    continue
                self._backfill_log_row(log_row, strategy)
        except Exception as exc:
            log_external_failure("performance_logs", exc, {"operation": "backfill"})

    def backfill_recommendation_cycles(self) -> None:
        try:
            cycles = self._open_recommendation_cycles(limit=500)
            for cycle in cycles:
                self._backfill_cycle_row(cycle)
        except Exception as exc:
            log_external_failure("recommendation_cycles", exc, {"operation": "backfill"})

    def _unevaluated_performance_logs(self, limit: int) -> list[dict[str, Any]]:
        lister = getattr(self.repository, "list_unevaluated_performance_logs", None)
        if lister is not None:
            return lister(limit=limit)
        return [
            row
            for row in self.repository.list_performance_logs(limit=limit)
            if row.get("price_after_20d") is None
        ]

    def _open_recommendation_cycles(self, limit: int) -> list[dict[str, Any]]:
        lister = getattr(self.repository, "list_open_recommendation_cycles", None)
        if lister is not None:
            return lister(limit=limit)
        return [
            row
            for row in self.repository.list_recommendation_cycles(limit=limit)
            if row.get("status") == "active" or row.get("price_after_60d") is None
        ]

    def _price_history(self, ticker: str, lookback_days: int) -> Any:
        market = infer_market(ticker)
        cache_key = (market, ticker, lookback_days)
        if cache_key not in self._history_cache:
            self._history_cache[cache_key] = self.market_data_service.fetch_price_history(
                market, ticker, lookback_days=lookback_days
            )
        return self._history_cache[cache_key]

    def _backfill_log_row(self, log_row: dict[str, Any], strategy: dict[str, Any]) -> None:
        ticker = strategy.get("ticker")
        if not ticker:
            return
        result = self._price_history(str(ticker), lookback_days=90)
        if result.dataframe.empty:
            return
        created_at = parse_iso_datetime(strategy.get("created_at") or log_row.get("created_at"))
        if created_at is None:
            return
        today = datetime.now(timezone.utc).date()
        future_rows = result.dataframe[
            (result.dataframe.index.date > created_at.date())
            & (result.dataframe.index.date <= today)
        ]
        updates: dict[str, Any] = {}
        base_price = log_row.get("price_at_recommendation") or strategy.get("current_price")
        if base_price is None:
            return
        for days in (1, 5, 20):
            price_field = f"price_after_{days}d"
            return_field = f"return_after_{days}d"
            if log_row.get(price_field) is not None or len(future_rows) < days:
                continue
            price = float(future_rows.iloc[days - 1]["close"])
            updates[price_field] = round(price, 4)
            updates[return_field] = round(
                ((price - float(base_price)) / float(base_price)) * 100, 4
            )
        if updates:
            updates["evaluated_at"] = datetime.now(timezone.utc).isoformat()
            self.repository.update_performance_log(log_row["id"], updates)

    def _backfill_cycle_row(self, cycle: dict[str, Any]) -> None:
        ticker = cycle.get("ticker")
        if not ticker:
            return
        result = self._price_history(str(ticker), lookback_days=160)
        if result.dataframe.empty:
            return
        started_at = parse_iso_datetime(cycle.get("started_at") or cycle.get("created_at"))
        if started_at is None:
            return
        today = datetime.now(timezone.utc).date()
        future_rows = result.dataframe[
            (result.dataframe.index.date > started_at.date())
            & (result.dataframe.index.date <= today)
        ]
        if future_rows.empty:
            return
        reference_price = cycle.get("reference_price")
        if reference_price is None:
            return
        reference_price = float(reference_price)
        updates: dict[str, Any] = {}
        for days in (1, 5, 20, 60):
            price_field = f"price_after_{days}d"
            return_field = f"return_after_{days}d"
            if cycle.get(price_field) is not None or len(future_rows) < days:
                continue
            price = float(future_rows.iloc[days - 1]["close"])
            updates[price_field] = round(price, 4)
            updates[return_field] = round(((price - reference_price) / reference_price) * 100, 4)

        if cycle.get("status") == "active":
            terminal_status = self._cycle_terminal_status(cycle, future_rows)
            if terminal_status:
                updates["status"] = terminal_status
                updates["closed_at"] = datetime.now(timezone.utc).isoformat()
            elif len(future_rows) >= horizon_days(cycle.get("horizon")):
                updates["status"] = "expired"
                updates["closed_at"] = datetime.now(timezone.utc).isoformat()

        if updates:
            updates["evaluated_at"] = datetime.now(timezone.utc).isoformat()
            self.repository.update_recommendation_cycle(cycle["id"], updates)

    def _cycle_terminal_status(
        self,
        cycle: dict[str, Any],
        future_rows: Any,
    ) -> str | None:
        target = cycle.get("target_price")
        stop = cycle.get("stop_loss")
        target_price = float(target) if target is not None else None
        stop_loss = float(stop) if stop is not None else None
        if target_price is None and stop_loss is None:
            return None
        for _, row in future_rows.iterrows():
            high = float(row.get("high", row.get("close")))
            low = float(row.get("low", row.get("close")))
            if stop_loss is not None and low <= stop_loss:
                return "hit_stop"
            if target_price is not None and high >= target_price:
                return "hit_target"
        return None
