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
        value_history_sources = []
        totals = {
            "total_market_value": 0.0,
            "total_cost": 0.0,
            "daily_profit_loss": 0.0,
            "previous_market_value": 0.0,
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
            price_result = self._price_result(asset)
            current_price_native = self._current_price(asset, avg_price, price_result)
            value_native = quantity * current_price_native
            cost = cost_native * fx_rate
            current_price = current_price_native * fx_rate
            value = value_native * fx_rate
            profit_loss = value - cost
            return_rate = (profit_loss / cost * 100) if cost else 0.0
            daily_change = self._daily_change(asset, quantity, fx_rate, price_result)
            daily_profit_loss = daily_change["profit_loss"]
            previous_value = value - daily_profit_loss
            market = asset.get("market")

            if market == "KR":
                totals["domestic_value"] += value
            elif market == "CASH":
                totals["cash_value"] += value
            else:
                totals["global_value"] += value

            totals["total_market_value"] += value
            totals["total_cost"] += cost
            totals["daily_profit_loss"] += daily_profit_loss
            totals["previous_market_value"] += previous_value
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
                    "daily_profit_loss": round(daily_profit_loss, 2),
                    "daily_return_rate": daily_change["return_rate"],
                    "previous_close_native": daily_change["previous_close_native"],
                }
            )
            value_history_sources.append(
                self._value_history_source(
                    asset,
                    quantity,
                    avg_price,
                    fx_rate,
                    value,
                    price_result,
                )
            )

        total_value = totals["total_market_value"]
        total_cost = totals["total_cost"]
        total_profit_loss = total_value - total_cost
        total_return_rate = (total_profit_loss / total_cost * 100) if total_cost else 0.0
        daily_profit_loss = totals["daily_profit_loss"]
        previous_value = totals["previous_market_value"]
        daily_return_rate = (daily_profit_loss / previous_value * 100) if previous_value else 0.0

        allocation = []
        for row in rows:
            weight = (row["market_value"] / total_value * 100) if total_value else 0.0
            allocation.append({**row, "weight": round(weight, 2)})

        latest_summary = None
        if latest_report:
            latest_summary = latest_report.get("summary")
            if not latest_summary and isinstance(latest_report.get("content"), dict):
                latest_summary = latest_report["content"].get("market_summary", {}).get("summary")

        snapshot_history = self._snapshot_value_history()
        value_history = (
            snapshot_history
            if len(snapshot_history) >= 2
            else self._portfolio_value_history(value_history_sources)
        )

        return PortfolioSummaryResponse(
            total_market_value=round(total_value, 2),
            total_cost=round(total_cost, 2),
            total_profit_loss=round(total_profit_loss, 2),
            total_return_rate=round(total_return_rate, 2),
            daily_profit_loss=round(daily_profit_loss, 2),
            daily_return_rate=round(daily_return_rate, 2),
            domestic_value=round(totals["domestic_value"], 2),
            global_value=round(totals["global_value"], 2),
            cash_value=round(totals["cash_value"], 2),
            base_currency="KRW",
            usd_krw_rate=round(usd_krw_rate, 4),
            daily_asset_changes=sorted(
                [
                    {
                        "ticker": row["ticker"],
                        "name": row["name"],
                        "market": row["market"],
                        "daily_profit_loss": row["daily_profit_loss"],
                        "daily_return_rate": row["daily_return_rate"],
                    }
                    for row in rows
                    if row["daily_profit_loss"] != 0
                ],
                key=lambda row: abs(row["daily_profit_loss"]),
                reverse=True,
            ),
            value_history=value_history,
            asset_allocation=allocation,
            asset_returns=rows,
            latest_report_summary=latest_summary,
        )

    def _price_result(self, asset: dict[str, Any]) -> Any | None:
        if asset.get("market") == "CASH" or self.market_data_service is None:
            return None
        try:
            return self.market_data_service.fetch_price_history(asset["market"], asset["ticker"])
        except Exception as exc:
            log_external_failure(
                "market_data",
                exc,
                {"operation": "portfolio_price_result", "ticker": asset.get("ticker")},
            )
            return None

    def _current_price(
        self, asset: dict[str, Any], fallback: float, price_result: Any | None
    ) -> float:
        if asset.get("market") == "CASH" or self.market_data_service is None:
            return fallback
        try:
            if (
                price_result
                and price_result.current_price is not None
                and not price_result.is_stale
            ):
                return float(price_result.current_price)
        except Exception as exc:
            log_external_failure(
                "market_data",
                exc,
                {"operation": "portfolio_current_price", "ticker": asset.get("ticker")},
            )
        return fallback

    def _daily_change(
        self,
        asset: dict[str, Any],
        quantity: float,
        fx_rate: float,
        price_result: Any | None,
    ) -> dict[str, Any]:
        if asset.get("market") == "CASH" or self.market_data_service is None:
            return {
                "profit_loss": 0.0,
                "return_rate": 0.0,
                "previous_close_native": None,
            }
        try:
            frame = price_result.dataframe if price_result else None
            if (
                price_result is None
                or price_result.is_stale
                or frame is None
                or frame.empty
                or "close" not in frame
                or len(frame) < 2
            ):
                return {
                    "profit_loss": 0.0,
                    "return_rate": 0.0,
                    "previous_close_native": None,
                }
            current_close = float(frame.iloc[-1]["close"])
            previous_close = float(frame.iloc[-2]["close"])
            profit_loss = (current_close - previous_close) * quantity * fx_rate
            previous_value = previous_close * quantity * fx_rate
            return_rate = (profit_loss / previous_value * 100) if previous_value else 0.0
            return {
                "profit_loss": round(profit_loss, 2),
                "return_rate": round(return_rate, 2),
                "previous_close_native": round(previous_close, 4),
            }
        except Exception as exc:
            log_external_failure(
                "market_data",
                exc,
                {"operation": "portfolio_daily_change", "ticker": asset.get("ticker")},
            )
            return {
                "profit_loss": 0.0,
                "return_rate": 0.0,
                "previous_close_native": None,
            }

    def _value_history_source(
        self,
        asset: dict[str, Any],
        quantity: float,
        avg_price: float,
        fx_rate: float,
        current_value: float,
        price_result: Any | None,
    ) -> dict[str, Any]:
        if asset.get("market") == "CASH":
            return {"kind": "cash", "current_value": current_value}
        if (
            price_result is None
            or price_result.dataframe.empty
            or "close" not in price_result.dataframe
        ):
            fallback_value = quantity * avg_price * fx_rate
            return {"kind": "cash", "current_value": fallback_value}
        frame = price_result.dataframe.tail(35)
        values = {
            index.date().isoformat(): round(float(row["close"]) * quantity * fx_rate, 2)
            for index, row in frame.iterrows()
        }
        return {"kind": "market", "values": values, "current_value": current_value}

    def _portfolio_value_history(self, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        market_dates = sorted(
            {
                date
                for source in sources
                if source.get("kind") == "market"
                for date in source.get("values", {})
            }
        )[-30:]
        if not market_dates:
            total_value = sum(float(source.get("current_value") or 0) for source in sources)
            return [
                {
                    "date": "",
                    "total_market_value": round(total_value, 2),
                    "daily_profit_loss": 0.0,
                    "daily_return_rate": 0.0,
                }
            ]

        history = []
        previous_total = None
        for date in market_dates:
            total = 0.0
            for source in sources:
                if source.get("kind") == "cash":
                    total += float(source.get("current_value") or 0)
                    continue
                values = source.get("values", {})
                available_dates = [candidate for candidate in values if candidate <= date]
                if available_dates:
                    total += float(values[max(available_dates)])
            daily_profit_loss = 0.0 if previous_total is None else total - previous_total
            daily_return_rate = (
                (daily_profit_loss / previous_total * 100) if previous_total else 0.0
            )
            history.append(
                {
                    "date": date,
                    "total_market_value": round(total, 2),
                    "daily_profit_loss": round(daily_profit_loss, 2),
                    "daily_return_rate": round(daily_return_rate, 2),
                }
            )
            previous_total = total
        return history

    def _snapshot_value_history(self) -> list[dict[str, Any]]:
        try:
            snapshots = self.repository.list_portfolio_snapshots(limit=90)
        except Exception as exc:
            log_external_failure(
                "portfolio_snapshots",
                exc,
                {"operation": "list_portfolio_snapshots"},
            )
            return []
        rows = sorted(
            snapshots,
            key=lambda row: (
                row.get("snapshot_date") or self._date_from_iso(row.get("created_at")),
                row.get("created_at") or "",
            ),
        )[-60:]
        history = []
        previous_total = None
        for row in rows:
            total = float(row.get("total_market_value") or 0)
            daily_profit_loss = 0.0 if previous_total is None else total - previous_total
            daily_return_rate = (
                (daily_profit_loss / previous_total * 100) if previous_total else 0.0
            )
            history.append(
                {
                    "date": row.get("snapshot_date") or self._date_from_iso(row.get("created_at")),
                    "created_at": row.get("created_at"),
                    "report_type": row.get("report_type"),
                    "source": "snapshot",
                    "total_market_value": round(total, 2),
                    "daily_profit_loss": round(daily_profit_loss, 2),
                    "daily_return_rate": round(daily_return_rate, 2),
                }
            )
            previous_total = total
        return history

    def _date_from_iso(self, value: Any) -> str:
        text = str(value or "")
        return text[:10] if len(text) >= 10 else ""

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
