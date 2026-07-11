"""Deterministic, leakage-resistant helpers for time-series backtest validation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import pandas as pd

MarketRegime = Literal["bull", "bear", "sideways", "high_volatility"]


def classify_market_regime(
    history: pd.DataFrame,
    as_of_position: int | None = None,
    *,
    trend_window: int = 20,
    volatility_window: int = 20,
    trend_threshold: float = 0.03,
    annualized_volatility_threshold: float = 0.35,
) -> MarketRegime:
    """Classify a market using close prices available at or before ``as_of_position``.

    High volatility takes precedence. Otherwise the trailing return determines bull or bear;
    observations without enough history, or with a return inside the threshold, are sideways.
    """

    if history is None or history.empty or "close" not in history.columns:
        return "sideways"
    if trend_window < 2 or volatility_window < 2:
        raise ValueError("trend_window and volatility_window must be at least 2")
    if as_of_position is None:
        as_of_position = len(history) - 1
    if as_of_position < 0 or as_of_position >= len(history):
        raise IndexError("as_of_position is outside history")

    close = pd.to_numeric(history.iloc[: as_of_position + 1]["close"], errors="coerce").dropna()
    if len(close) < 2:
        return "sideways"

    volatility_returns = close.pct_change().dropna().tail(volatility_window)
    if len(volatility_returns) >= volatility_window:
        annualized_volatility = float(volatility_returns.std(ddof=0) * (252**0.5))
        if annualized_volatility >= annualized_volatility_threshold:
            return "high_volatility"

    if len(close) <= trend_window:
        return "sideways"
    trailing_return = float(close.iloc[-1] / close.iloc[-(trend_window + 1)] - 1)
    if trailing_return >= trend_threshold:
        return "bull"
    if trailing_return <= -trend_threshold:
        return "bear"
    return "sideways"


def create_walk_forward_folds(
    samples: Sequence[Mapping[str, Any]],
    *,
    train_size: int,
    test_size: int,
    forward_days: int,
    step_size: int | None = None,
) -> dict[str, Any]:
    """Create expanding walk-forward folds with a purged train/test boundary.

    Samples must already be in chronological order. Fold boundaries use unique decision dates,
    never split one date across train/test, and exclude rows whose ``label_end_date`` reaches the
    test start. ``forward_days`` is an additional embargo measured in unique decision dates.
    """

    if train_size <= 0 or test_size <= 0 or forward_days < 0:
        raise ValueError("train_size/test_size must be positive and forward_days non-negative")
    resolved_step_size = test_size if step_size is None else step_size
    if resolved_step_size <= 0:
        raise ValueError("step_size must be positive")
    if any(
        samples[index].get("date") > samples[index + 1].get("date")
        for index in range(len(samples) - 1)
    ):
        raise ValueError("samples must be sorted chronologically")

    unique_dates = list(dict.fromkeys(str(sample.get("date")) for sample in samples))
    minimum_samples = train_size + forward_days + test_size
    if len(unique_dates) < minimum_samples:
        return {
            "folds": [],
            "reason": (
                "insufficient decision dates: "
                f"need at least {minimum_samples}, received {len(unique_dates)}"
            ),
        }

    folds = []
    test_start = train_size + forward_days
    while test_start + test_size <= len(unique_dates):
        test_dates = set(unique_dates[test_start : test_start + test_size])
        test_start_date = unique_dates[test_start]
        allowed_train_dates = set(unique_dates[: test_start - forward_days])
        train_indices = []
        purged_indices = []
        test_indices = []
        for index, sample in enumerate(samples):
            decision_date = str(sample.get("date"))
            if decision_date in test_dates:
                test_indices.append(index)
                continue
            if decision_date >= test_start_date:
                continue
            label_end_date = str(sample.get("label_end_date") or decision_date)
            if decision_date in allowed_train_dates and label_end_date < test_start_date:
                train_indices.append(index)
            else:
                purged_indices.append(index)
        if not train_indices or not test_indices:
            test_start += resolved_step_size
            continue
        folds.append(
            {
                "fold": len(folds),
                "train_indices": train_indices,
                "purged_indices": purged_indices,
                "test_indices": test_indices,
                "train_start_date": samples[train_indices[0]].get("date"),
                "train_end_date": samples[train_indices[-1]].get("date"),
                "test_start_date": samples[test_indices[0]].get("date"),
                "test_end_date": samples[test_indices[-1]].get("date"),
            }
        )
        test_start += resolved_step_size
    return {
        "folds": folds,
        "reason": None if folds else "no leakage-free fold with non-empty train and test sets",
    }


def aggregate_validation_results(samples: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate sample count and average net return by action, market, and regime."""

    grouped: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for sample in samples:
        grouped[(str(sample["action"]), str(sample["market"]), str(sample["regime"]))].append(
            float(sample["net_return"])
        )
    return [
        {
            "action": action,
            "market": market,
            "regime": regime,
            "sample_count": len(returns),
            "avg_net_return": round(sum(returns) / len(returns), 8),
        }
        for (action, market, regime), returns in sorted(grouped.items())
    ]


def calculate_baseline_returns(
    history: pd.DataFrame,
    decision_position: int,
    forward_days: int,
    *,
    sma_window: int = 20,
    momentum_window: int = 20,
) -> dict[str, float | int]:
    """Calculate forward directional returns for three deterministic baselines.

    Signals use closes through ``decision_position`` only. Future closes are used solely to form
    the evaluation label. Returns are decimal values, not percentages.
    """

    if "close" not in history.columns:
        raise ValueError("history must contain a close column")
    if forward_days <= 0 or sma_window <= 0 or momentum_window <= 0:
        raise ValueError("forward_days and lookback windows must be positive")
    if decision_position < max(sma_window - 1, momentum_window):
        raise ValueError("insufficient pre-decision history for baseline signals")
    future_position = decision_position + forward_days
    if decision_position < 0 or future_position >= len(history):
        raise ValueError("insufficient forward history for baseline return")

    close = pd.to_numeric(history["close"], errors="coerce")
    available = close.iloc[: decision_position + 1]
    if available.tail(max(sma_window, momentum_window + 1)).isna().any():
        raise ValueError("baseline lookback contains missing close values")
    entry_position = decision_position + 1
    entry_column = "open" if "open" in history.columns else "close"
    entry_price = float(pd.to_numeric(history[entry_column], errors="coerce").iloc[entry_position])
    future_price = float(close.iloc[future_position])
    signal_price = float(available.iloc[-1])
    if pd.isna(future_price) or pd.isna(entry_price) or entry_price <= 0:
        raise ValueError("baseline prices must be present and entry price must be positive")

    forward_return = future_price / entry_price - 1
    sma_value = float(available.tail(sma_window).mean())
    sma_direction = 1 if signal_price >= sma_value else -1
    momentum_start = float(available.iloc[-(momentum_window + 1)])
    momentum_direction = 1 if signal_price >= momentum_start else -1
    return {
        "buy_and_hold": forward_return,
        "sma_trend": sma_direction * forward_return,
        "simple_momentum": momentum_direction * forward_return,
        "sma_direction": sma_direction,
        "momentum_direction": momentum_direction,
    }
