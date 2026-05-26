from typing import Any

from app.config import get_env_application_defaults, resolve_application_settings
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
        app_settings = resolve_application_settings(
            self.repository.get_settings(),
            get_env_application_defaults(),
        )
        usd_krw_rate = float(app_settings.usd_krw_rate)
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
            currency = self._asset_currency(asset)
            fx_rate = self._fx_rate(asset, currency, usd_krw_rate)
            cost_native = quantity * avg_price
            current_price_native = self._current_price(asset, avg_price)
            value_native = quantity * current_price_native
            cost = cost_native * fx_rate
            current_price = current_price_native * fx_rate
            value = value_native * fx_rate
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
                    "currency": currency,
                    "fx_rate": round(fx_rate, 4),
                    "base_currency": "KRW",
                    "avg_price_native": round(avg_price, 4),
                    "current_price_native": round(current_price_native, 4),
                    "current_price": round(current_price, 2),
                    "market_value_native": round(value_native, 2),
                    "cost_native": round(cost_native, 2),
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
            base_currency="KRW",
            usd_krw_rate=round(usd_krw_rate, 4),
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

    def _asset_currency(self, asset: dict[str, Any]) -> str:
        currency = str(asset.get("currency") or "").strip().upper()
        if currency:
            return currency
        if str(asset.get("market") or "").upper() in {"US", "ETF"}:
            return "USD"
        return "KRW"

    def _fx_rate(self, asset: dict[str, Any], currency: str, usd_krw_rate: float) -> float:
        market = str(asset.get("market") or "").upper()
        if currency == "USD" or market in {"US", "ETF"}:
            return usd_krw_rate
        return 1.0
