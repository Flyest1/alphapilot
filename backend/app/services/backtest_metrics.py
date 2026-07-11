"""Pure performance and cost metrics for historical decision-support analysis.

Public API:

``estimate_round_trip_cost_pct(...)`` returns a percentage-point cost breakdown for
one completed recommendation observation. It is an analytical estimate, not an order
or execution model.

``calculate_backtest_metrics(samples)`` accepts observations containing at least
``date`` (ISO date), ``gross_return_pct``, and ``net_return_pct``. Each observation may
also provide ``turnover`` as gross exposure changed; the conservative default is 2.0
for one complete enter-and-exit observation. The result contains matching ``gross``
and ``net`` metric dictionaries plus turnover and recommendation-frequency summaries.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np
import pandas as pd

UNKNOWN_LIQUIDITY_SLIPPAGE_PCT = 0.25


def estimate_liquidity_slippage_pct(
    average_trading_value: float | None,
) -> float:
    """Return a conservative round-trip slippage estimate in percentage points.

    ``average_trading_value`` is expected in KRW-equivalent notional. Unknown liquidity
    deliberately receives a conservative default rather than a zero estimate.
    """

    if average_trading_value is None or not np.isfinite(average_trading_value):
        return UNKNOWN_LIQUIDITY_SLIPPAGE_PCT
    if average_trading_value <= 0:
        return 0.5
    if average_trading_value < 100_000_000:
        return 0.5
    if average_trading_value < 1_000_000_000:
        return 0.3
    if average_trading_value < 10_000_000_000:
        return 0.15
    return 0.08


def estimate_round_trip_cost_pct(
    *,
    action: str,
    market: str,
    fee_rate_pct: float,
    kr_tax_rate_pct: float,
    fx_spread_pct: float,
    average_trading_value: float | None = None,
) -> dict[str, float]:
    """Estimate round-trip analytical costs in percentage points.

    The same round-trip convention applies to long-oriented BUY/HOLD/WATCH and
    short-oriented SELL/REDUCE recommendations. ``fee_rate_pct`` is one-way,
    ``kr_tax_rate_pct`` is charged once for KR disposal, and ``fx_spread_pct`` is
    a one-way setting applied twice for a round-trip USD conversion.
    """

    normalized_action = action.upper()
    if normalized_action not in {"BUY", "HOLD", "WATCH", "SELL", "REDUCE"}:
        raise ValueError(f"Unsupported recommendation action: {action}")
    normalized_market = market.upper()
    fee_cost = max(float(fee_rate_pct), 0.0) * 2
    tax_cost = max(float(kr_tax_rate_pct), 0.0) if normalized_market == "KR" else 0.0
    fx_cost = max(float(fx_spread_pct), 0.0) * 2 if normalized_market in {"US", "ETF"} else 0.0
    slippage_cost = estimate_liquidity_slippage_pct(average_trading_value)
    total_cost = fee_cost + tax_cost + fx_cost + slippage_cost
    return {
        "fee_pct": round(fee_cost, 6),
        "kr_tax_pct": round(tax_cost, 6),
        "fx_spread_pct": round(fx_cost, 6),
        "slippage_pct": round(slippage_cost, 6),
        "total_cost_pct": round(total_cost, 6),
    }


def calculate_backtest_metrics(
    samples: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Calculate gross/net historical metrics from dated recommendation observations.

    Return schema::

        {
          "sample_count": int,
          "start_date": str | None,
          "end_date": str | None,
          "gross": { ... return and risk metrics ... },
          "net": { ... return and risk metrics ... },
          "turnover": {"total": float, "annualized": float | None},
          "recommendation_frequency": {"annualized": float | None,
                                       "per_active_month": float},
        }

    Return observations are treated as a chronological analytical series. This
    function does not model orders, fills, quantities, or portfolio execution.
    """

    frame = _samples_frame(samples)
    if frame.empty:
        return {
            "sample_count": 0,
            "start_date": None,
            "end_date": None,
            "gross": _empty_return_metrics(),
            "net": _empty_return_metrics(),
            "turnover": {"total": 0.0, "annualized": None},
            "recommendation_frequency": {"annualized": None, "per_active_month": 0.0},
        }

    elapsed_years = _elapsed_years(frame["date"])
    total_turnover = float(frame["turnover"].sum())
    annualized_turnover = total_turnover / elapsed_years if elapsed_years else None
    active_months = max(int(frame["date"].dt.to_period("M").nunique()), 1)
    return {
        "sample_count": len(frame),
        "start_date": frame.iloc[0]["date"].date().isoformat(),
        "end_date": frame.iloc[-1]["date"].date().isoformat(),
        "gross": _return_metrics(frame, "gross_return_pct", elapsed_years),
        "net": _return_metrics(frame, "net_return_pct", elapsed_years),
        "turnover": {
            "total": round(total_turnover, 6),
            "annualized": _rounded(annualized_turnover),
        },
        "recommendation_frequency": {
            "annualized": _rounded(len(frame) / elapsed_years if elapsed_years else None),
            "per_active_month": round(len(frame) / active_months, 6),
        },
    }


def _samples_frame(samples: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    rows = list(samples)
    if not rows:
        return pd.DataFrame(columns=["date", "gross_return_pct", "net_return_pct", "turnover"])
    required = {"date", "gross_return_pct", "net_return_pct"}
    for row in rows:
        missing = required.difference(row)
        if missing:
            raise ValueError(f"Backtest sample missing required fields: {sorted(missing)}")
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"], errors="raise", utc=True).dt.tz_localize(None)
    for column in ("gross_return_pct", "net_return_pct"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not np.isfinite(frame[column]).all():
            raise ValueError(f"Backtest sample contains non-finite {column}")
        if (frame[column] <= -100).any():
            raise ValueError(f"Backtest sample {column} must be greater than -100")
    if "turnover" not in frame:
        frame["turnover"] = 2.0
    else:
        frame["turnover"] = pd.to_numeric(frame["turnover"], errors="raise").fillna(2.0)
        if (frame["turnover"] < 0).any() or not np.isfinite(frame["turnover"]).all():
            raise ValueError("Backtest sample turnover must be finite and non-negative")
    return frame.sort_values("date", kind="stable").reset_index(drop=True)


def _return_metrics(
    frame: pd.DataFrame,
    return_column: str,
    elapsed_years: float | None,
) -> dict[str, Any]:
    returns = frame[return_column].to_numpy(dtype=float) / 100
    wealth = np.cumprod(1 + returns)
    cumulative_return = float(wealth[-1] - 1)
    annualized_return = None
    if elapsed_years and wealth[-1] > 0:
        annualized_return = float(wealth[-1] ** (1 / elapsed_years) - 1)

    periods_per_year = len(returns) / elapsed_years if elapsed_years else None
    standard_deviation = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    sharpe = None
    if periods_per_year and standard_deviation > 0:
        sharpe = float(np.mean(returns) / standard_deviation * np.sqrt(periods_per_year))
    downside = np.minimum(returns, 0)
    downside_deviation = float(np.sqrt(np.mean(np.square(downside))))
    sortino = None
    if periods_per_year and downside_deviation > 0:
        sortino = float(np.mean(returns) / downside_deviation * np.sqrt(periods_per_year))

    max_drawdown, recovery_days = _drawdown_metrics(frame["date"], wealth)
    calmar = None
    if annualized_return is not None and max_drawdown < 0:
        calmar = annualized_return / abs(max_drawdown)

    gains = returns[returns > 0]
    losses = returns[returns < 0]
    gross_profit = float(gains.sum())
    gross_loss = float(abs(losses.sum()))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    tail_count = max(1, int(np.ceil(len(returns) * 0.1)))
    bottom_decile_average = float(np.sort(returns)[:tail_count].mean())
    return {
        "cumulative_return_pct": _percent(cumulative_return),
        "annualized_return_pct": _percent(annualized_return),
        "sharpe": _rounded(sharpe),
        "sortino": _rounded(sortino),
        "calmar": _rounded(calmar),
        "max_drawdown_pct": _percent(max_drawdown),
        "recovery_days": recovery_days,
        "hit_rate": round(float((returns > 0).mean()), 6),
        "average_gain_pct": _percent(float(gains.mean()) if len(gains) else None),
        "average_loss_pct": _percent(float(losses.mean()) if len(losses) else None),
        "expectancy_pct": _percent(float(returns.mean())),
        "profit_factor": _rounded(profit_factor),
        "worst_month": _worst_period(frame["date"], returns, "M"),
        "worst_quarter": _worst_period(frame["date"], returns, "Q"),
        "bottom_10pct_average_pct": _percent(bottom_decile_average),
    }


def _drawdown_metrics(dates: pd.Series, wealth: np.ndarray) -> tuple[float, int | None]:
    wealth_with_origin = np.concatenate(([1.0], wealth))
    running_peak = np.maximum.accumulate(wealth_with_origin)
    drawdowns = wealth_with_origin / running_peak - 1
    trough_index = int(np.argmin(drawdowns))
    max_drawdown = float(drawdowns[trough_index])
    if max_drawdown == 0:
        return 0.0, 0
    peak_index = int(np.argmax(wealth_with_origin[: trough_index + 1]))
    recovery_candidates = np.flatnonzero(
        wealth_with_origin[trough_index + 1 :] >= wealth_with_origin[peak_index]
    )
    if not len(recovery_candidates):
        return max_drawdown, None
    end_index = trough_index + 1 + int(recovery_candidates[0])
    indexed_dates = pd.DatetimeIndex([dates.iloc[0], *dates.tolist()])
    recovery_days = int((indexed_dates[end_index] - indexed_dates[peak_index]).days)
    return max_drawdown, recovery_days


def _worst_period(dates: pd.Series, returns: np.ndarray, frequency: str) -> dict[str, Any] | None:
    if not len(returns):
        return None
    series = pd.Series(returns, index=pd.DatetimeIndex(dates))
    periods = series.index.to_period(frequency)
    compounded = series.groupby(periods).apply(lambda values: (1 + values).prod() - 1)
    worst_period = compounded.idxmin()
    return {
        "period": str(worst_period),
        "return_pct": _percent(float(compounded.loc[worst_period])),
    }


def _elapsed_years(dates: pd.Series) -> float | None:
    if len(dates) < 2:
        return None
    elapsed_days = int((dates.iloc[-1] - dates.iloc[0]).days)
    return elapsed_days / 365.25 if elapsed_days > 0 else None


def _empty_return_metrics() -> dict[str, Any]:
    return {
        "cumulative_return_pct": 0.0,
        "annualized_return_pct": None,
        "sharpe": None,
        "sortino": None,
        "calmar": None,
        "max_drawdown_pct": 0.0,
        "recovery_days": 0,
        "hit_rate": 0.0,
        "average_gain_pct": None,
        "average_loss_pct": None,
        "expectancy_pct": 0.0,
        "profit_factor": None,
        "worst_month": None,
        "worst_quarter": None,
        "bottom_10pct_average_pct": None,
    }


def _percent(value: float | None) -> float | None:
    return round(value * 100, 6) if value is not None and np.isfinite(value) else None


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None and np.isfinite(value) else None
