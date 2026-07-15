"""Pure portfolio-risk calculations for decision-support position sizing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite
from typing import Any

import numpy as np
import pandas as pd

from app.services.backtest_metrics import estimate_round_trip_cost_pct
from app.utils.tickers import normalize_ticker

CASH_DEPLOY_RATIO = {"conservative": 0.1, "balanced": 0.2, "aggressive": 0.3}
MIN_RETURN_OBSERVATIONS = 20
MIN_EV_OUTCOME_SAMPLES = 30
CORRELATION_THRESHOLD = 0.7
SECTOR_EXPOSURE_LIMIT = 0.4
LIQUIDITY_CAP_RATIO = 0.01
CONSTRAINT_LABELS = {
    "fixed_risk": "개별 손실 예산",
    "remaining_portfolio_loss": "남은 포트폴리오 손실 예산",
    "remaining_cash": "남은 현금 예산",
    "max_asset": "단일 자산 비중",
    "market_room": "시장 배분 여유",
    "currency_room": "통화 배분 여유",
    "sector_room": "섹터 집중도",
    "liquidity": "평균 거래대금",
    "beta": "포트폴리오 베타",
    "correlated_factor": "동일 팩터 상관 노출",
    "expected_value": "비용 차감 기대값",
}


def _finite_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None


def _round_or_none(value: float | None, digits: int = 6) -> float | None:
    return round(value, digits) if value is not None and isfinite(value) else None


def _frame_columns(frame: Any) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty or "close" not in frame:
        return pd.DataFrame(columns=["close", "open", "volume"])
    columns = [column for column in ("close", "open", "volume") if column in frame]
    normalized = frame[columns].copy()
    normalized.index = pd.to_datetime(normalized.index)
    for column in columns:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    return normalized.sort_index()


def _returns(frame: pd.DataFrame) -> pd.Series:
    if frame.empty or "close" not in frame:
        return pd.Series(dtype=float)
    close = frame["close"].where(np.isfinite(frame["close"]))
    return close.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna()


def _aligned_correlation(first: pd.Series, second: pd.Series) -> tuple[float | None, int]:
    paired = pd.concat([first.rename("first"), second.rename("second")], axis=1).dropna()
    if len(paired) < MIN_RETURN_OBSERVATIONS:
        return None, len(paired)
    if paired["first"].nunique() < 2 or paired["second"].nunique() < 2:
        return None, len(paired)
    value = paired["first"].corr(paired["second"])
    return (_finite_float(value), len(paired))


def _beta(asset_returns: pd.Series, proxy_returns: pd.Series) -> tuple[float | None, int]:
    paired = pd.concat(
        [asset_returns.rename("asset"), proxy_returns.rename("proxy")], axis=1
    ).dropna()
    if len(paired) < MIN_RETURN_OBSERVATIONS:
        return None, len(paired)
    variance = float(paired["proxy"].var(ddof=0))
    if not isfinite(variance) or variance <= 0:
        return None, len(paired)
    covariance = float(paired["asset"].cov(paired["proxy"], ddof=0))
    value = covariance / variance
    return (_finite_float(value), len(paired))


def _asset_key(asset: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(asset.get("market") or "").upper(),
        normalize_ticker(str(asset.get("ticker") or "")),
    )


def _allocation_value_by_key(portfolio_summary: Mapping[str, Any]) -> dict[tuple[str, str], float]:
    values: dict[tuple[str, str], float] = {}
    for row in portfolio_summary.get("asset_allocation") or []:
        key = _asset_key(row)
        value = _finite_float(row.get("market_value")) or 0.0
        values[key] = values.get(key, 0.0) + value
    return values


def _exposure_values(portfolio_summary: Mapping[str, Any], field: str) -> dict[str, float]:
    values: dict[str, float] = {}
    for row in portfolio_summary.get(field) or []:
        key = str(row.get("key") or "")
        value = _finite_float(row.get("value"))
        if key and value is not None:
            values[key] = value
    return values


def _cash_values_by_currency(portfolio_summary: Mapping[str, Any]) -> dict[str, float]:
    values: dict[str, float] = {}
    for row in portfolio_summary.get("asset_allocation") or []:
        if str(row.get("market") or "").upper() != "CASH":
            continue
        currency = str(row.get("currency") or "KRW").upper()
        value = _finite_float(row.get("market_value")) or 0.0
        values[currency] = values.get(currency, 0.0) + value
    if not values:
        fallback = _finite_float(portfolio_summary.get("cash_value")) or 0.0
        if fallback > 0:
            values["KRW"] = fallback
    return values


def _market_bucket(market: str) -> str | None:
    if market == "KR":
        return "domestic"
    if market in {"US", "ETF"}:
        return "global"
    return None


def _currency_bucket(currency: str) -> str | None:
    if currency == "KRW":
        return "domestic"
    if currency == "USD":
        return "global"
    return None


def _currency_target_pct(currency: str, app_settings: Any) -> float | None:
    if currency == "USD":
        return float(app_settings.target_global_pct)
    return None


def _cost_market(asset: Mapping[str, Any]) -> str:
    market = str(asset.get("market") or "").upper()
    if market == "ETF" and str(asset.get("currency") or "").upper() == "KRW":
        return "KR"
    return market


def _risk_metrics(
    frame: Any,
    current_price: float,
    stop_loss: float,
    currency: str,
    usd_krw_rate: float,
) -> tuple[dict[str, Any], pd.Series]:
    stop_distance = (current_price - stop_loss) / current_price
    normalized = _frame_columns(frame)
    returns = _returns(normalized)
    trailing_returns = returns.tail(MIN_RETURN_OBSERVATIONS)
    sufficient_returns = len(trailing_returns) >= MIN_RETURN_OBSERVATIONS
    daily_std = float(trailing_returns.std(ddof=0)) if sufficient_returns else None
    daily_std = _finite_float(daily_std)

    gap_risk = None
    if sufficient_returns and "open" in normalized:
        previous_close = normalized["close"].shift(1)
        gaps = ((normalized["open"] / previous_close) - 1).abs()
        gaps = gaps.replace([np.inf, -np.inf], np.nan).dropna().tail(MIN_RETURN_OBSERVATIONS)
        if len(gaps) >= MIN_RETURN_OBSERVATIONS:
            gap_risk = _finite_float(float(gaps.max()))

    risk_distances = [stop_distance]
    if daily_std is not None:
        risk_distances.append(2 * daily_std)
    if gap_risk is not None:
        risk_distances.append(gap_risk)
    effective_downside = max(risk_distances)

    average_traded_value = None
    liquidity_cap = None
    if "volume" in normalized:
        traded = (normalized["close"] * normalized["volume"]).replace([np.inf, -np.inf], np.nan)
        traded = traded.dropna().tail(MIN_RETURN_OBSERVATIONS)
        if len(traded) >= MIN_RETURN_OBSERVATIONS:
            average_traded_value = _finite_float(float(traded.mean()))
            if average_traded_value is not None:
                if currency == "USD":
                    average_traded_value *= usd_krw_rate
                liquidity_cap = average_traded_value * LIQUIDITY_CAP_RATIO

    return (
        {
            "return_observations": int(len(returns)),
            "volatility_status": "available" if daily_std is not None else "unavailable",
            "daily_volatility_pct": _round_or_none(
                daily_std * 100 if daily_std is not None else None
            ),
            "gap_risk_status": "available" if gap_risk is not None else "unavailable",
            "gap_risk_pct": _round_or_none(gap_risk * 100 if gap_risk is not None else None),
            "stop_distance_pct": _round_or_none(stop_distance * 100),
            "effective_downside_pct": _round_or_none(effective_downside * 100),
            "average_traded_value_20_krw": _round_or_none(average_traded_value, 2),
            "liquidity_status": "available" if liquidity_cap is not None else "unavailable",
        },
        returns,
    )


def _constraint(amount: float | None, available: bool = True) -> dict[str, Any]:
    return {
        "status": "available" if available else "unavailable",
        "amount": _round_or_none(max(amount, 0.0), 0) if amount is not None else None,
    }


class PortfolioRiskService:
    """Calculate review ceilings without orders, quantities, or execution behavior."""

    def calculate_position_sizing(
        self,
        *,
        strategies: Sequence[Any],
        analysis_rows: Sequence[Mapping[str, Any]],
        portfolio_summary: Mapping[str, Any],
        app_settings: Any,
        owned_tickers: set[str],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        total_value = _finite_float(portfolio_summary.get("total_market_value")) or 0.0
        cash_value = _finite_float(portfolio_summary.get("cash_value")) or 0.0
        cash_ratio = CASH_DEPLOY_RATIO.get(str(app_settings.risk_profile), 0.2)
        risk_budget = total_value * float(app_settings.risk_per_trade_pct) / 100
        remaining_loss_budget = risk_budget
        remaining_cash = cash_value * cash_ratio
        usd_krw_rate = _finite_float(getattr(app_settings, "usd_krw_rate", None)) or 0.0

        rows_by_ticker: dict[str, Mapping[str, Any]] = {}
        for row in analysis_rows:
            ticker = normalize_ticker(str(row["asset"].get("ticker") or ""))
            existing = rows_by_ticker.get(ticker)
            if existing is None or (
                existing["asset"].get("id") is not None and row["asset"].get("id") is None
            ):
                rows_by_ticker[ticker] = row
        held_rows = [
            row
            for row in analysis_rows
            if normalize_ticker(str(row["asset"].get("ticker") or "")) in owned_tickers
            and str(row["asset"].get("market") or "").upper() != "CASH"
            and not bool(getattr(row.get("market_data"), "is_stale", True))
        ]
        held_returns = {
            _asset_key(row["asset"]): _returns(
                _frame_columns(getattr(row["market_data"], "dataframe", None))
            )
            for row in held_rows
        }
        allocation_values = _allocation_value_by_key(portfolio_summary)
        expected_held_keys = {key for key in allocation_values if key[0] != "CASH"} or set(
            held_returns
        )
        usable_held_keys = {
            key for key, returns in held_returns.items() if len(returns) >= MIN_RETURN_OBSERVATIONS
        }
        missing_held_keys = sorted(expected_held_keys - usable_held_keys)
        risk_context_complete = not missing_held_keys
        proxy = self._equal_weight_proxy(
            [returns for key, returns in held_returns.items() if key in usable_held_keys]
        )
        sector_values = _exposure_values(portfolio_summary, "sector_exposure")
        currency_values = _exposure_values(portfolio_summary, "currency_exposure")
        cash_values = _cash_values_by_currency(portfolio_summary)
        remaining_cash_by_currency = {
            currency: value * cash_ratio for currency, value in cash_values.items()
        }
        results: dict[str, dict[str, Any]] = {}
        candidate_evaluations: list[dict[str, Any]] = []

        for strategy in strategies:
            ticker = normalize_ticker(str(getattr(strategy, "ticker", "")))
            row = rows_by_ticker.get(ticker)
            if ticker in owned_tickers or getattr(strategy, "action", None) not in {"BUY", "WATCH"}:
                continue
            exclusion_reason = self._candidate_exclusion_reason(strategy, row)
            if exclusion_reason is not None:
                candidate_evaluations.append(
                    {"ticker": ticker, "status": "excluded", "reason": exclusion_reason}
                )
                continue
            asset = row["asset"]
            market_data = row["market_data"]
            current_price = float(strategy.current_price)
            stop_loss = float(strategy.stop_loss)
            target_price = _finite_float(getattr(strategy, "target_price", None))
            currency = str(asset.get("currency") or "KRW").upper()
            candidate_cash_available = self._candidate_cash_available(
                currency,
                remaining_cash,
                remaining_cash_by_currency,
            )
            metrics, candidate_returns = _risk_metrics(
                getattr(market_data, "dataframe", None),
                current_price,
                stop_loss,
                currency,
                usd_krw_rate,
            )
            effective_downside = float(metrics["effective_downside_pct"]) / 100
            fixed_risk_cap = risk_budget / effective_downside if effective_downside > 0 else 0.0
            remaining_loss_cap = (
                remaining_loss_budget / effective_downside if effective_downside > 0 else 0.0
            )
            constraints = self._constraints(
                asset=asset,
                current_price=current_price,
                target_price=target_price,
                candidate_returns=candidate_returns,
                proxy_returns=proxy,
                held_returns=held_returns,
                risk_context_complete=risk_context_complete,
                missing_held_keys=missing_held_keys,
                allocation_values=allocation_values,
                sector_values=sector_values,
                currency_values=currency_values,
                total_value=total_value,
                fixed_risk_cap=fixed_risk_cap,
                remaining_loss_cap=remaining_loss_cap,
                remaining_cash=candidate_cash_available,
                metrics=metrics,
                app_settings=app_settings,
                strategy=strategy,
            )
            cost_breakdown = constraints.pop("cost_breakdown")
            correlation_metrics = constraints.pop("correlation_metrics")
            correlations = [
                item["correlation"]
                for item in correlation_metrics.get("correlations", [])
                if item.get("correlation") is not None
            ]
            correlation_status = correlation_metrics.get("status")
            metrics["beta"] = (
                correlation_metrics.get("beta") if correlation_status == "available" else None
            )
            metrics["max_correlation"] = (
                max(correlations) if correlations and correlation_status == "available" else None
            )
            outcome = self._expected_value(
                strategy=strategy,
                target_price=target_price,
                effective_downside=effective_downside,
                cost=cost_breakdown,
            )
            if outcome["status"] == "available" and float(outcome["value_pct"]) <= 0:
                constraints["expected_value"] = _constraint(0.0)
            else:
                constraints["expected_value"] = _constraint(None, available=False)
            available_caps = [
                float(value["amount"])
                for value in constraints.values()
                if isinstance(value, Mapping)
                and value.get("status") == "available"
                and value.get("amount") is not None
            ]
            suggested = min(available_caps) if available_caps else 0.0
            binding = self._binding_constraint(constraints, suggested)
            remaining_loss_budget = max(0.0, remaining_loss_budget - suggested * effective_downside)
            remaining_cash = max(0.0, remaining_cash - suggested)
            self._consume_cash(currency, suggested, remaining_cash_by_currency)

            results[ticker] = {
                "suggested_max_amount": _round_or_none(suggested, 0),
                "risk_cap_amount": _round_or_none(fixed_risk_cap, 0),
                "cash_cap_amount": _round_or_none(candidate_cash_available, 0),
                "risk_budget_amount": _round_or_none(risk_budget, 0),
                "risk_per_trade_pct": float(app_settings.risk_per_trade_pct),
                "cash_deploy_ratio": cash_ratio,
                "stop_distance_pct": metrics["stop_distance_pct"],
                "currency": "KRW",
                "method": "fixed-fractional-portfolio-risk",
                "binding_constraint": binding,
                "binding_constraint_label": CONSTRAINT_LABELS.get(binding, binding),
                "constraints": constraints,
                "risk_metrics": metrics,
                "cost_breakdown": cost_breakdown,
                "correlation_metrics": correlation_metrics,
                "expected_value": outcome,
                "review_only": True,
                "combinable": False,
            }
            candidate_evaluations.append(
                {
                    "ticker": ticker,
                    "status": "sized",
                    "suggested_max_amount": _round_or_none(suggested, 0),
                    "binding_constraint": binding,
                }
            )

        snapshot = {
            "model_version": "portfolio-risk-v1",
            "allocation_policy": "report_order_sequential",
            "candidate_order": [row["ticker"] for row in candidate_evaluations],
            "candidate_evaluations": candidate_evaluations,
            "risk_per_trade_pct": float(app_settings.risk_per_trade_pct),
            "cash_deploy_ratio": cash_ratio,
            "target_domestic_pct": float(app_settings.target_domestic_pct),
            "target_global_pct": float(app_settings.target_global_pct),
            "target_cash_pct": float(app_settings.target_cash_pct),
            "target_max_asset_pct": float(app_settings.target_max_asset_pct),
            "rebalance_band_pct": float(app_settings.rebalance_band_pct),
            "usd_krw_rate": usd_krw_rate,
            "fee_rate_pct": float(app_settings.fee_rate_pct),
            "kr_tax_rate_pct": float(app_settings.kr_tax_rate_pct),
            "fx_spread_pct": float(app_settings.fx_spread_pct),
            "sector_exposure_limit_pct": SECTOR_EXPOSURE_LIMIT * 100,
            "correlation_threshold": CORRELATION_THRESHOLD,
            "liquidity_cap_ratio": LIQUIDITY_CAP_RATIO,
            "initial_loss_budget_amount": _round_or_none(risk_budget, 0),
            "initial_cash_budget_amount": _round_or_none(cash_value * cash_ratio, 0),
            "remaining_loss_budget_amount": _round_or_none(remaining_loss_budget, 0),
            "remaining_cash_budget_amount": _round_or_none(remaining_cash, 0),
            "initial_cash_by_currency": {
                currency: _round_or_none(value * cash_ratio, 0)
                for currency, value in cash_values.items()
            },
            "remaining_cash_by_currency": {
                currency: _round_or_none(value, 0)
                for currency, value in remaining_cash_by_currency.items()
            },
            "minimum_return_observations": MIN_RETURN_OBSERVATIONS,
            "minimum_ev_outcome_samples": MIN_EV_OUTCOME_SAMPLES,
            "risk_context_status": "complete" if risk_context_complete else "partial",
            "expected_held_asset_count": len(expected_held_keys),
            "usable_held_asset_count": len(usable_held_keys),
            "missing_held_assets": [
                {"market": market, "ticker": ticker} for market, ticker in missing_held_keys
            ],
        }
        return results, snapshot

    def _candidate_exclusion_reason(
        self,
        strategy: Any,
        row: Mapping[str, Any] | None,
    ) -> str | None:
        current_price = _finite_float(getattr(strategy, "current_price", None))
        stop_loss = _finite_float(getattr(strategy, "stop_loss", None))
        if row is None:
            return "missing_analysis_row"
        if getattr(strategy, "reasoning", "") == "data-limited":
            return "data_limited_strategy"
        if bool(getattr(row.get("market_data"), "is_stale", True)):
            return "stale_market_data"
        technical = row.get("technical_analysis")
        if getattr(technical, "trend_label", "") == "data-limited":
            return "data_limited_technical_analysis"
        if current_price is None or current_price <= 0:
            return "invalid_current_price"
        if stop_loss is None or stop_loss >= current_price:
            return "invalid_stop_loss"
        return None

    def _candidate_cash_available(
        self,
        currency: str,
        remaining_cash: float,
        remaining_cash_by_currency: Mapping[str, float],
    ) -> float:
        same_currency = max(float(remaining_cash_by_currency.get(currency, 0.0)), 0.0)
        if currency == "USD":
            convertible_krw = max(float(remaining_cash_by_currency.get("KRW", 0.0)), 0.0)
            return min(remaining_cash, same_currency + convertible_krw)
        return min(remaining_cash, same_currency)

    def _consume_cash(
        self,
        currency: str,
        amount: float,
        remaining_cash_by_currency: dict[str, float],
    ) -> None:
        remaining = max(amount, 0.0)
        currencies = [currency, "KRW"] if currency == "USD" else [currency]
        for source_currency in dict.fromkeys(currencies):
            available = max(float(remaining_cash_by_currency.get(source_currency, 0.0)), 0.0)
            consumed = min(available, remaining)
            remaining_cash_by_currency[source_currency] = available - consumed
            remaining -= consumed
            if remaining <= 0:
                break

    def _equal_weight_proxy(self, returns: Sequence[pd.Series]) -> pd.Series:
        usable = [series.rename(index) for index, series in enumerate(returns) if not series.empty]
        if not usable:
            return pd.Series(dtype=float)
        return pd.concat(usable, axis=1).mean(axis=1, skipna=True).dropna()

    def _constraints(
        self,
        *,
        asset: Mapping[str, Any],
        current_price: float,
        target_price: float | None,
        candidate_returns: pd.Series,
        proxy_returns: pd.Series,
        held_returns: Mapping[tuple[str, str], pd.Series],
        risk_context_complete: bool,
        missing_held_keys: Sequence[tuple[str, str]],
        allocation_values: Mapping[tuple[str, str], float],
        sector_values: Mapping[str, float],
        currency_values: Mapping[str, float],
        total_value: float,
        fixed_risk_cap: float,
        remaining_loss_cap: float,
        remaining_cash: float,
        metrics: Mapping[str, Any],
        app_settings: Any,
        strategy: Any,
    ) -> dict[str, Any]:
        market = str(asset.get("market") or "").upper()
        currency = str(asset.get("currency") or "KRW").upper()
        constraints: dict[str, Any] = {
            "fixed_risk": _constraint(fixed_risk_cap),
            "remaining_portfolio_loss": _constraint(remaining_loss_cap),
            "remaining_cash": _constraint(remaining_cash),
        }
        current_asset_value = allocation_values.get(_asset_key(asset), 0.0)
        max_asset = (
            total_value * float(app_settings.target_max_asset_pct) / 100 - current_asset_value
        )
        constraints["max_asset"] = _constraint(max_asset)

        market_bucket = _market_bucket(market)
        if market_bucket is not None:
            target = float(getattr(app_settings, f"target_{market_bucket}_pct"))
            constraints["market_room"] = _constraint(
                total_value * (target + float(app_settings.rebalance_band_pct)) / 100
                - self._summary_value(market_bucket, asset, allocation_values, total_value)
            )
        else:
            constraints["market_room"] = _constraint(None, available=False)

        currency_target = _currency_target_pct(currency, app_settings)
        if currency == "KRW":
            constraints["currency_room"] = _constraint(remaining_cash)
        elif _currency_bucket(currency) is not None and currency_target is not None:
            constraints["currency_room"] = _constraint(
                total_value
                * min(100.0, currency_target + float(app_settings.rebalance_band_pct))
                / 100
                - float(currency_values.get(currency, 0.0))
            )
        else:
            constraints["currency_room"] = _constraint(None, available=False)

        sector = str(asset.get("sector") or "").strip()
        if sector:
            constraints["sector_room"] = _constraint(
                total_value * SECTOR_EXPOSURE_LIMIT - float(sector_values.get(sector, 0.0))
            )
        else:
            constraints["sector_room"] = _constraint(None, available=False)

        liquidity_cap = None
        average_traded = metrics.get("average_traded_value_20_krw")
        if average_traded is not None:
            liquidity_cap = float(average_traded) * LIQUIDITY_CAP_RATIO
        constraints["liquidity"] = _constraint(
            liquidity_cap,
            available=liquidity_cap is not None,
        )

        beta, beta_observations = _beta(candidate_returns, proxy_returns)
        constraints["beta"] = _constraint(
            (
                fixed_risk_cap / max(1.0, abs(beta))
                if beta is not None and risk_context_complete
                else None
            ),
            available=beta is not None and risk_context_complete,
        )
        correlations = []
        correlated_exposure = 0.0
        for key, held in held_returns.items():
            correlation, observations = _aligned_correlation(candidate_returns, held)
            correlations.append(
                {
                    "market": key[0],
                    "ticker": key[1],
                    "correlation": _round_or_none(correlation),
                    "observations": observations,
                }
            )
            if correlation is not None and correlation >= CORRELATION_THRESHOLD:
                correlated_exposure += float(allocation_values.get(key, 0.0))
        correlation_available = (
            risk_context_complete
            and bool(held_returns)
            and any(row["correlation"] is not None for row in correlations)
        )
        constraints["correlated_factor"] = _constraint(
            total_value * SECTOR_EXPOSURE_LIMIT - correlated_exposure,
            available=correlation_available,
        )
        cost = estimate_round_trip_cost_pct(
            action=str(getattr(strategy, "action", "WATCH")),
            market=_cost_market(asset),
            fee_rate_pct=float(app_settings.fee_rate_pct),
            kr_tax_rate_pct=float(app_settings.kr_tax_rate_pct),
            fx_spread_pct=float(app_settings.fx_spread_pct),
            average_trading_value=_finite_float(average_traded),
        )
        constraints["cost_breakdown"] = cost
        constraints["correlation_metrics"] = {
            "status": (
                "available"
                if correlation_available
                else "partial" if not risk_context_complete else "unavailable"
            ),
            "beta": _round_or_none(beta),
            "beta_observations": beta_observations,
            "correlations": correlations,
            "correlated_exposure_amount": _round_or_none(correlated_exposure, 0),
            "missing_held_assets": [
                {"market": market, "ticker": ticker} for market, ticker in missing_held_keys
            ],
        }
        return constraints

    def _summary_value(
        self,
        market_bucket: str,
        asset: Mapping[str, Any],
        allocation_values: Mapping[tuple[str, str], float],
        total_value: float,
    ) -> float:
        if market_bucket == "domestic":
            return sum(value for (market, _), value in allocation_values.items() if market == "KR")
        if market_bucket == "global":
            return sum(
                value for (market, _), value in allocation_values.items() if market in {"US", "ETF"}
            )
        return total_value if asset.get("market") == "CASH" else 0.0

    def _expected_value(
        self,
        *,
        strategy: Any,
        target_price: float | None,
        effective_downside: float,
        cost: Mapping[str, Any],
    ) -> dict[str, Any]:
        detail = getattr(strategy, "confidence_detail", None) or {}
        sample_size = _finite_float(detail.get("outcome_sample_size"))
        target_frequency = _finite_float(detail.get("target_hit_frequency"))
        stop_frequency = _finite_float(detail.get("stop_hit_frequency"))
        other_frequency = _finite_float(detail.get("other_closed_frequency"))
        current_price = _finite_float(getattr(strategy, "current_price", None))
        if (
            sample_size is None
            or sample_size < MIN_EV_OUTCOME_SAMPLES
            or target_frequency is None
            or stop_frequency is None
            or other_frequency is None
            or not 0 <= target_frequency <= 1
            or not 0 <= stop_frequency <= 1
            or not 0 <= other_frequency <= 1
            or abs(target_frequency + stop_frequency + other_frequency - 1.0) > 0.001
            or target_price is None
            or current_price is None
            or current_price <= 0
            or target_price <= current_price
        ):
            return {
                "status": "insufficient_sample",
                "value_pct": None,
                "outcome_sample_size": int(sample_size or 0),
            }
        upside = (target_price - current_price) / current_price * 100
        downside = effective_downside * 100
        cost_pct = _finite_float(cost.get("total_cost_pct")) or 0.0
        value = target_frequency * upside - stop_frequency * downside - cost_pct
        return {
            "status": "available",
            "value_pct": _round_or_none(value),
            "expected_value_pct": _round_or_none(value),
            "outcome_sample_size": int(sample_size),
            "sample_size": int(sample_size),
            "target_hit_frequency": _round_or_none(target_frequency),
            "stop_hit_frequency": _round_or_none(stop_frequency),
            "other_frequency": _round_or_none(other_frequency),
            "other_outcome_assumption": "zero_gross_return",
            "upside_pct": _round_or_none(upside),
            "downside_pct": _round_or_none(downside),
            "cost_pct": _round_or_none(cost_pct),
        }

    @staticmethod
    def _binding_constraint(constraints: Mapping[str, Any], suggested: float) -> str | None:
        candidates = [
            name
            for name, value in constraints.items()
            if isinstance(value, Mapping)
            and value.get("status") == "available"
            and value.get("amount") is not None
            and float(value["amount"]) == suggested
        ]
        return candidates[0] if candidates else None
