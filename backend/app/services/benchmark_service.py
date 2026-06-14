from datetime import datetime, timezone
from typing import Any

from app.db.supabase_client import Repository
from app.services.market_data_service import MarketDataService, MarketDataResult
from app.utils.datetime import parse_iso_datetime
from app.utils.logging import log_external_failure
from app.utils.tickers import infer_market


class BenchmarkService:
    def __init__(
        self,
        repository: Repository,
        market_data_service: MarketDataService | None = None,
    ) -> None:
        self.repository = repository
        self.market_data_service = market_data_service or MarketDataService()

    def get_return_series(self, days: int = 60) -> dict[str, Any]:
        safe_days = max(7, min(int(days or 60), 180))
        series = [
            self._market_index_series("kospi", "KOSPI", "domestic", "KOSPI", safe_days),
            self._market_index_series("kosdaq", "KOSDAQ", "domestic", "KOSDAQ", safe_days),
            self._market_index_series("sp500", "S&P 500", "global", "S&P 500", safe_days),
            self._market_index_series("nasdaq", "NASDAQ", "global", "NASDAQ", safe_days),
            self._alphapilot_series(safe_days),
            self._actual_portfolio_series(safe_days),
        ]
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days": safe_days,
            "series": [row for row in series if row["points"]],
            "assumptions": [
                "AlphaPilot 운용 수익률은 추천 cycle 기준가 대비 평균 추천 성과입니다.",
                "내 실제 수익률은 portfolio_snapshots 총 평가금액 기준 누적 수익률입니다.",
                "미국 증시 대표선은 S&P 500을 사용합니다.",
            ],
        }

    def _market_index_series(
        self,
        key: str,
        label: str,
        report_type: str,
        index_label: str,
        days: int,
    ) -> dict[str, Any]:
        try:
            results = self.market_data_service.fetch_major_indices(
                report_type,
                lookback_days=days + 20,
                stale_data_business_days=5,
            )
            result = results.get(index_label)
            return {
                "key": key,
                "label": label,
                "points": self._result_to_return_points(result, days),
            }
        except Exception as exc:
            log_external_failure(
                "benchmark",
                exc,
                {"operation": "market_index_series", "label": label},
            )
            return {"key": key, "label": label, "points": []}

    def _result_to_return_points(
        self,
        result: MarketDataResult | None,
        days: int,
    ) -> list[dict[str, Any]]:
        if result is None or result.dataframe.empty or "close" not in result.dataframe:
            return []
        frame = result.dataframe.sort_index().tail(days)
        if frame.empty:
            return []
        base = float(frame.iloc[0]["close"])
        if base <= 0:
            return []
        return [
            {
                "date": index.date().isoformat(),
                "return_rate": round(((float(row["close"]) - base) / base) * 100, 4),
            }
            for index, row in frame.iterrows()
        ]

    def _actual_portfolio_series(self, days: int) -> dict[str, Any]:
        try:
            snapshots = self.repository.list_portfolio_snapshots(limit=days + 30)
        except Exception as exc:
            log_external_failure(
                "benchmark",
                exc,
                {"operation": "actual_portfolio_series"},
            )
            return {"key": "actual_portfolio", "label": "내 실제 수익률", "points": []}
        rows = sorted(
            snapshots,
            key=lambda row: (
                row.get("snapshot_date") or self._date_from_iso(row.get("created_at")),
                row.get("created_at") or "",
            ),
        )[-days:]
        if not rows:
            return {"key": "actual_portfolio", "label": "내 실제 수익률", "points": []}
        base = float(rows[0].get("total_market_value") or 0)
        if base <= 0:
            return {"key": "actual_portfolio", "label": "내 실제 수익률", "points": []}
        return {
            "key": "actual_portfolio",
            "label": "내 실제 수익률",
            "points": [
                {
                    "date": row.get("snapshot_date") or self._date_from_iso(row.get("created_at")),
                    "return_rate": round(
                        ((float(row.get("total_market_value") or 0) - base) / base) * 100,
                        4,
                    ),
                }
                for row in rows
            ],
        }

    def _alphapilot_series(self, days: int) -> dict[str, Any]:
        try:
            cycles = self.repository.list_recommendation_cycles(limit=50)
        except Exception as exc:
            log_external_failure("benchmark", exc, {"operation": "alphapilot_cycles"})
            return {"key": "alphapilot", "label": "AlphaPilot 운용 수익률", "points": []}
        daily_returns: dict[str, list[float]] = {}
        for cycle in cycles:
            reference_price = cycle.get("reference_price")
            ticker = cycle.get("ticker")
            if not ticker or reference_price is None or float(reference_price) <= 0:
                continue
            started_at = parse_iso_datetime(cycle.get("started_at") or cycle.get("created_at"))
            if started_at is None:
                continue
            result = self._cycle_market_result(str(ticker), days + 30)
            if result is None or result.dataframe.empty or "close" not in result.dataframe:
                continue
            frame = result.dataframe.sort_index()
            started_date = started_at.date()
            frame = frame[frame.index.date >= started_date].tail(days)
            for index, row in frame.iterrows():
                daily_returns.setdefault(index.date().isoformat(), []).append(
                    ((float(row["close"]) - float(reference_price)) / float(reference_price)) * 100
                )
        points = [
            {"date": date, "return_rate": round(sum(values) / len(values), 4)}
            for date, values in sorted(daily_returns.items())[-days:]
            if values
        ]
        return {"key": "alphapilot", "label": "AlphaPilot 운용 수익률", "points": points}

    def _cycle_market_result(self, ticker: str, lookback_days: int) -> MarketDataResult | None:
        try:
            market = infer_market(ticker)
            return self.market_data_service.fetch_price_history(
                market,
                ticker,
                lookback_days=lookback_days,
                stale_data_business_days=5,
            )
        except Exception as exc:
            log_external_failure(
                "benchmark",
                exc,
                {"operation": "cycle_market_result", "ticker": ticker},
            )
            return None

    def _date_from_iso(self, value: Any) -> str:
        text = str(value or "")
        return text[:10] if len(text) >= 10 else ""
