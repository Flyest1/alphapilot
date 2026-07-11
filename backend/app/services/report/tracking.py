"""performance_logs / recommendation_cycles 백필과 사이클 상태 동기화 모듈.

리포트 생성 시마다 호출되므로, 평가가 끝나지 않은 행만 조회하고
같은 티커의 가격 이력은 한 번만 조회해 재사용한다.
"""

from datetime import date, datetime, time, timezone
from typing import Any

from app.db.supabase_client import Repository
from app.services.market_data_service import MarketDataService
from app.utils.datetime import parse_iso_datetime
from app.utils.logging import log_external_failure
from app.utils.tickers import infer_market

HORIZON_DAYS = {"short": 5, "medium": 20, "long": 60}
SHORT_ACTIONS = {"SELL", "REDUCE"}


def horizon_days(horizon: Any) -> int:
    return HORIZON_DAYS.get(str(horizon or "medium"), 20)


def evaluate_barriers(
    action: str,
    target_price: float | None,
    stop_loss: float | None,
    future_rows: Any,
) -> tuple[str, str] | None:
    if target_price is None and stop_loss is None:
        return None
    is_short = str(action or "").upper() in SHORT_ACTIONS
    for trading_day, row in future_rows.sort_index().iterrows():
        high = float(row.get("high", row.get("close")))
        low = float(row.get("low", row.get("close")))
        if is_short:
            favorable_hit = target_price is not None and low <= target_price
            adverse_hit = stop_loss is not None and high >= stop_loss
        else:
            favorable_hit = target_price is not None and high >= target_price
            adverse_hit = stop_loss is not None and low <= stop_loss

        if not favorable_hit and not adverse_hit:
            continue

        barrier_hit_at = trading_timestamp(trading_day)
        if favorable_hit and adverse_hit:
            return "ambiguous", barrier_hit_at
        if favorable_hit:
            return "hit_target", barrier_hit_at
        return "hit_stop", barrier_hit_at
    return None


def trading_timestamp(value: Any) -> str:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, date):
        timestamp = datetime.combine(value, time.min)
    else:
        timestamp = parse_iso_datetime(value)
        if timestamp is None:
            raise ValueError(f"Unsupported trading date: {value!r}")
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat()


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

    def recalculate_recommendation_cycles(self, limit: int = 1000) -> int:
        cycles = self.repository.list_recommendation_cycles(limit=limit)
        recalculated = 0
        reset_fields = {
            "status": "active",
            "closed_at": None,
            "barrier_hit_at": None,
            "price_after_1d": None,
            "price_after_5d": None,
            "price_after_20d": None,
            "price_after_60d": None,
            "return_after_1d": None,
            "return_after_5d": None,
            "return_after_20d": None,
            "return_after_60d": None,
            "evaluated_at": None,
        }
        for cycle in cycles:
            if cycle.get("status") == "superseded":
                continue
            reset_cycle = {**cycle, **reset_fields}
            if self._backfill_cycle_row(reset_cycle, initial_updates=reset_fields):
                recalculated += 1
        return recalculated

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

    def _backfill_cycle_row(
        self,
        cycle: dict[str, Any],
        initial_updates: dict[str, Any] | None = None,
    ) -> bool:
        ticker = cycle.get("ticker")
        if not ticker:
            return False
        started_at = parse_iso_datetime(cycle.get("started_at") or cycle.get("created_at"))
        if started_at is None:
            return False
        today = datetime.now(timezone.utc).date()
        age_days = max(0, (today - started_at.date()).days)
        result = self._price_history(str(ticker), lookback_days=max(160, age_days + 30))
        if result.dataframe.empty:
            return False
        future_rows = result.dataframe[
            (result.dataframe.index.date > started_at.date())
            & (result.dataframe.index.date <= today)
        ]
        if future_rows.empty:
            return False
        reference_price = cycle.get("reference_price")
        if reference_price is None:
            return False
        reference_price = float(reference_price)
        updates: dict[str, Any] = dict(initial_updates or {})
        for days in (1, 5, 20, 60):
            price_field = f"price_after_{days}d"
            return_field = f"return_after_{days}d"
            if cycle.get(price_field) is not None or len(future_rows) < days:
                continue
            price = float(future_rows.iloc[days - 1]["close"])
            updates[price_field] = round(price, 4)
            updates[return_field] = round(((price - reference_price) / reference_price) * 100, 4)

        if cycle.get("status") == "active":
            terminal_result = self._cycle_terminal_status(cycle, future_rows)
            if terminal_result:
                terminal_status, barrier_hit_at = terminal_result
                updates["status"] = terminal_status
                updates["barrier_hit_at"] = barrier_hit_at
                updates["closed_at"] = barrier_hit_at
            elif len(future_rows) >= horizon_days(cycle.get("horizon")):
                expiry_index = horizon_days(cycle.get("horizon")) - 1
                updates["status"] = "expired"
                updates["closed_at"] = trading_timestamp(future_rows.index[expiry_index])

        if updates:
            updates["evaluated_at"] = datetime.now(timezone.utc).isoformat()
            self.repository.update_recommendation_cycle(cycle["id"], updates)
            return True
        return False

    def _cycle_terminal_status(
        self,
        cycle: dict[str, Any],
        future_rows: Any,
    ) -> tuple[str, str] | None:
        target = cycle.get("target_price")
        stop = cycle.get("stop_loss")
        target_price = float(target) if target is not None else None
        stop_loss = float(stop) if stop is not None else None
        return evaluate_barriers(
            str(cycle.get("action") or ""),
            target_price,
            stop_loss,
            future_rows,
        )
