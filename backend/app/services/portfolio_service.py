from datetime import datetime, timezone
from typing import Any

from app.config import get_env_application_defaults, resolve_application_settings
from app.db.supabase_client import Repository
from app.models.portfolio import PortfolioSummaryResponse
from app.utils.assets import held_assets
from app.utils.logging import log_external_failure

# 집중도 경고 임계치 (Phase 4-3). 단일 종목 임계치는 설정 target_max_asset_pct를 따른다.
SINGLE_SECTOR_WEIGHT_WARNING = 40.0
UNCLASSIFIED_SECTOR = "미분류"

MARKET_LABELS = {"KR": "국내", "US": "미국", "ETF": "미국 ETF", "CASH": "현금"}
ALLOCATION_BUCKET_LABELS = {"domestic": "국내", "global": "글로벌", "cash": "현금"}


class PortfolioService:
    def __init__(self, repository: Repository, market_data_service: Any | None = None) -> None:
        self.repository = repository
        self.market_data_service = market_data_service

    def get_summary(self) -> PortfolioSummaryResponse:
        assets = held_assets(self.repository.list_assets())
        latest_report = self.repository.get_latest_report()
        app_settings = resolve_application_settings(
            self.repository.get_settings(),
            get_env_application_defaults(),
        )
        usd_krw_rate = self._resolve_usd_krw_rate(app_settings)
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
                    "sector": asset.get("sector"),
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

        net_totals = self._apply_cost_adjusted_returns(rows, app_settings)

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

        exposures = self._exposures(allocation, app_settings.target_max_asset_pct)
        drift = self._allocation_drift(totals, total_value, app_settings)

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
            currency_exposure=exposures["currency"],
            market_exposure=exposures["market"],
            sector_exposure=exposures["sector"],
            concentration_warnings=exposures["warnings"],
            allocation_drift=drift["rows"],
            rebalance_suggestions=drift["suggestions"],
            total_net_profit_loss=round(net_totals["net_profit_loss"], 2),
            total_net_return_rate=round(net_totals["net_return_rate"], 2),
        )

    def _apply_cost_adjusted_returns(
        self,
        rows: list[dict[str, Any]],
        app_settings: Any,
    ) -> dict[str, float]:
        """수수료/거래세/환전 스프레드를 차감한 추정 수익률을 행마다 채운다 (Phase 5-4).

        매수측 비용은 매입금액, 매도측 비용은 현재 평가금액 기준의 추정치다.
        """
        fee = float(app_settings.fee_rate_pct) / 100
        kr_tax = float(app_settings.kr_tax_rate_pct) / 100
        fx_spread = float(app_settings.fx_spread_pct) / 100
        total_net_profit = 0.0
        total_cost = 0.0
        for row in rows:
            cost = float(row.get("cost") or 0)
            value = float(row.get("market_value") or 0)
            total_cost += cost
            if row.get("market") == "CASH":
                row["estimated_costs"] = 0.0
                row["net_profit_loss"] = row.get("profit_loss", 0.0)
                row["net_return_rate"] = row.get("return_rate", 0.0)
                total_net_profit += float(row.get("profit_loss") or 0)
                continue
            is_usd = str(row.get("currency") or "") == "USD"
            buy_side = cost * (fee + (fx_spread if is_usd else 0))
            sell_side = value * (
                fee + (kr_tax if row.get("market") == "KR" else 0) + (fx_spread if is_usd else 0)
            )
            estimated_costs = buy_side + sell_side
            net_profit = float(row.get("profit_loss") or 0) - estimated_costs
            row["estimated_costs"] = round(estimated_costs, 2)
            row["net_profit_loss"] = round(net_profit, 2)
            row["net_return_rate"] = round((net_profit / cost * 100) if cost else 0.0, 2)
            total_net_profit += net_profit
        return {
            "net_profit_loss": total_net_profit,
            "net_return_rate": (total_net_profit / total_cost * 100) if total_cost else 0.0,
        }

    def _allocation_drift(
        self,
        totals: dict[str, float],
        total_value: float,
        app_settings: Any,
    ) -> dict[str, Any]:
        """목표 배분 대비 드리프트와 리밸런스 제안 문구를 계산한다 (Phase 5-2)."""
        targets = {
            "domestic": float(app_settings.target_domestic_pct),
            "global": float(app_settings.target_global_pct),
            "cash": float(app_settings.target_cash_pct),
        }
        actuals = {
            "domestic": (totals["domestic_value"] / total_value * 100) if total_value else 0.0,
            "global": (totals["global_value"] / total_value * 100) if total_value else 0.0,
            "cash": (totals["cash_value"] / total_value * 100) if total_value else 0.0,
        }
        band = float(app_settings.rebalance_band_pct)
        drift_rows = []
        suggestions = []
        for key, label in ALLOCATION_BUCKET_LABELS.items():
            drift_value = actuals[key] - targets[key]
            exceeded = total_value > 0 and abs(drift_value) > band
            drift_rows.append(
                {
                    "key": key,
                    "label": label,
                    "target_pct": round(targets[key], 2),
                    "actual_pct": round(actuals[key], 2),
                    "drift_pct": round(drift_value, 2),
                    "exceeded": exceeded,
                }
            )
            if not exceeded:
                continue
            gap = f"목표({targets[key]:.0f}%)보다 {abs(drift_value):.1f}%p"
            if drift_value > 0:
                advice = (
                    "추천 후보 중심의 분할 매수를 검토하세요."
                    if key == "cash"
                    else "비중 축소를 검토하세요."
                )
                suggestions.append(f"{label} 비중이 {gap} 높습니다. {advice}")
            else:
                advice = (
                    "현금 확보를 검토하세요."
                    if key == "cash"
                    else "분할 매수로 비중 확대를 검토하세요."
                )
                suggestions.append(f"{label} 비중이 {gap} 낮습니다. {advice}")
        return {"rows": drift_rows, "suggestions": suggestions}

    def _exposures(
        self,
        allocation: list[dict[str, Any]],
        max_asset_pct: float,
    ) -> dict[str, Any]:
        """통화/시장/섹터 노출 비중과 집중도 경고를 계산한다 (Phase 4-3)."""

        def grouped(key_fn: Any, label_fn: Any = None) -> list[dict[str, Any]]:
            buckets: dict[str, dict[str, float]] = {}
            for row in allocation:
                key = key_fn(row)
                bucket = buckets.setdefault(key, {"value": 0.0, "weight": 0.0})
                bucket["value"] += float(row.get("market_value") or 0)
                bucket["weight"] += float(row.get("weight") or 0)
            return sorted(
                [
                    {
                        "key": key,
                        "label": label_fn(key) if label_fn else key,
                        "value": round(bucket["value"], 2),
                        "weight": round(bucket["weight"], 2),
                    }
                    for key, bucket in buckets.items()
                ],
                key=lambda item: item["value"],
                reverse=True,
            )

        currency_exposure = grouped(lambda row: str(row.get("currency") or "KRW"))
        market_exposure = grouped(
            lambda row: str(row.get("market") or "기타"),
            lambda key: MARKET_LABELS.get(key, key),
        )
        sector_exposure = grouped(
            lambda row: (
                "현금"
                if row.get("market") == "CASH"
                else str(row.get("sector") or UNCLASSIFIED_SECTOR)
            )
        )

        warnings = []
        for row in allocation:
            weight = float(row.get("weight") or 0)
            if row.get("market") != "CASH" and weight > max_asset_pct:
                warnings.append(
                    f"단일 종목 {row.get('ticker')} 비중이 {weight:.1f}%로 "
                    f"{max_asset_pct:.0f}%를 초과합니다. 분산을 검토하세요."
                )
        for item in sector_exposure:
            if item["key"] in {"현금", UNCLASSIFIED_SECTOR}:
                continue
            if item["weight"] > SINGLE_SECTOR_WEIGHT_WARNING:
                warnings.append(
                    f"{item['label']} 섹터 비중이 {item['weight']:.1f}%로 "
                    f"{SINGLE_SECTOR_WEIGHT_WARNING:.0f}%를 초과합니다. 섹터 분산을 검토하세요."
                )
        return {
            "currency": currency_exposure,
            "market": market_exposure,
            "sector": sector_exposure,
            "warnings": warnings,
        }

    def create_snapshot(self) -> dict[str, Any]:
        summary = self.get_summary()
        snapshot = self.repository.create_portfolio_snapshot(
            {
                "report_id": None,
                "report_type": "manual",
                "snapshot_date": datetime.now(timezone.utc).date().isoformat(),
                "total_market_value": summary.total_market_value,
                "total_cost": summary.total_cost,
                "total_profit_loss": summary.total_profit_loss,
                "total_return_rate": summary.total_return_rate,
                "daily_profit_loss": summary.daily_profit_loss,
                "daily_return_rate": summary.daily_return_rate,
                "domestic_value": summary.domestic_value,
                "global_value": summary.global_value,
                "cash_value": summary.cash_value,
                "usd_krw_rate": summary.usd_krw_rate,
                "asset_allocation": summary.asset_allocation,
                "asset_returns": summary.asset_returns,
            }
        )
        return {"snapshot": snapshot, "summary": summary.model_dump(mode="json")}

    def _resolve_usd_krw_rate(self, app_settings: Any) -> float:
        fallback_rate = round(float(app_settings.usd_krw_rate), 4)
        if self.market_data_service is None or not hasattr(
            self.market_data_service, "fetch_usd_krw_rate"
        ):
            return fallback_rate
        try:
            latest_rate = self.market_data_service.fetch_usd_krw_rate(fallback_rate)
            if latest_rate is None or float(latest_rate) <= 0:
                return fallback_rate
            resolved_rate = round(float(latest_rate), 4)
            if abs(resolved_rate - fallback_rate) < 0.0001:
                return resolved_rate
            values = app_settings.model_dump(
                mode="json",
                exclude={"created_at", "updated_at"},
            )
            values["usd_krw_rate"] = resolved_rate
            self.repository.upsert_settings(values)
            return resolved_rate
        except Exception as exc:
            log_external_failure(
                "market_data",
                exc,
                {"operation": "portfolio_usd_krw_rate"},
            )
            return fallback_rate

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
