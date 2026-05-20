from typing import Any

from app.db.supabase_client import Repository
from app.models.portfolio import PortfolioSummaryResponse
from app.utils.logging import log_external_failure


class PortfolioService:
    def __init__(self, repository: Repository, market_data_service: Any | None = None) -> None:
        self.repository = repository
        self.market_data_service = market_data_service

    def get_summary(self) -> PortfolioSummaryResponse:
        assets = self.repository.list_assets()
        latest_report = self.repository.get_latest_report()
        rows = []
        totals = {
            "total_market_value": 0.0,
            "total_cost": 0.0,
            "domestic_value": 0.0,
            "global_value": 0.0,
            "cash_value": 0.0,
        }

        for asset in assets:
            quantity = float(asset.get("quantity") or 0)
            avg_price = float(asset.get("avg_price") or 0)
            cost = quantity * avg_price
            current_price = self._current_price(asset, avg_price)
            value = quantity * current_price
            profit_loss = value - cost
            return_rate = (profit_loss / cost * 100) if cost else 0.0
            market = asset.get("market")

            if market == "KR":
                totals["domestic_value"] += value
            elif market == "CASH":
                totals["cash_value"] += value
            else:
                totals["global_value"] += value

            totals["total_market_value"] += value
            totals["total_cost"] += cost
            rows.append(
                {
                    "ticker": asset.get("ticker"),
                    "name": asset.get("name"),
                    "market": market,
                    "market_value": round(value, 2),
                    "cost": round(cost, 2),
                    "profit_loss": round(profit_loss, 2),
                    "return_rate": round(return_rate, 2),
                }
            )

        total_value = totals["total_market_value"]
        total_cost = totals["total_cost"]
        total_profit_loss = total_value - total_cost
        total_return_rate = (total_profit_loss / total_cost * 100) if total_cost else 0.0

        allocation = []
        for row in rows:
            weight = (row["market_value"] / total_value * 100) if total_value else 0.0
            allocation.append({**row, "weight": round(weight, 2)})

        latest_summary = None
        if latest_report:
            latest_summary = latest_report.get("summary")
            if not latest_summary and isinstance(latest_report.get("content"), dict):
                latest_summary = latest_report["content"].get("market_summary", {}).get("summary")

        return PortfolioSummaryResponse(
            total_market_value=round(total_value, 2),
            total_cost=round(total_cost, 2),
            total_profit_loss=round(total_profit_loss, 2),
            total_return_rate=round(total_return_rate, 2),
            domestic_value=round(totals["domestic_value"], 2),
            global_value=round(totals["global_value"], 2),
            cash_value=round(totals["cash_value"], 2),
            asset_allocation=allocation,
            asset_returns=rows,
            latest_report_summary=latest_summary,
        )

    def _current_price(self, asset: dict[str, Any], fallback: float) -> float:
        if asset.get("market") == "CASH" or self.market_data_service is None:
            return fallback
        try:
            result = self.market_data_service.fetch_price_history(asset["market"], asset["ticker"])
            if result.current_price is not None and not result.is_stale:
                return float(result.current_price)
        except Exception as exc:
            log_external_failure(
                "market_data",
                exc,
                {"operation": "portfolio_current_price", "ticker": asset.get("ticker")},
            )
        return fallback
