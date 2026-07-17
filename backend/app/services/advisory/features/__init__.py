"""Deterministic, read-only ETF and sector decision-support features."""

from __future__ import annotations

import re
from typing import Any, Iterable

import numpy as np
import pandas as pd


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def rounded(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None and np.isfinite(value) else None


def close_series(frame: pd.DataFrame | None) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype=float)
    column = next(
        (name for name in ("close", "Close", "adj_close", "Adj Close") if name in frame),
        None,
    )
    if column is None:
        return pd.Series(dtype=float)
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return values.sort_index()


def period_return(close: pd.Series, sessions: int) -> float | None:
    if len(close) <= sessions:
        return None
    start = finite_number(close.iloc[-sessions - 1])
    end = finite_number(close.iloc[-1])
    if start is None or end is None or start <= 0:
        return None
    return (end / start - 1) * 100


def annualized_volatility(close: pd.Series, sessions: int = 252) -> float | None:
    if len(close) < 3:
        return None
    returns = close.pct_change().dropna().tail(sessions)
    if len(returns) < 2:
        return None
    value = float(returns.std(ddof=1) * np.sqrt(252) * 100)
    return value if np.isfinite(value) else None


def normalize_weight(value: Any) -> float | None:
    number = finite_number(value)
    if number is None or number < 0:
        return None
    return number * 100 if number <= 1 else number


def normalize_column_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).casefold())


def top_holdings_from_funds_data(
    funds_data: Any, limit: int = 10
) -> tuple[list[dict[str, Any]], str]:
    try:
        raw = getattr(funds_data, "top_holdings", None)
    except Exception:
        return [], "unavailable"
    if not isinstance(raw, pd.DataFrame) or raw.empty:
        return [], "unavailable"
    weight_column = next(
        (
            column
            for column in raw.columns
            if normalize_column_name(column)
            in {"holdingpercent", "weight", "weightpct", "percentage"}
        ),
        None,
    )
    if weight_column is None:
        return [], "unavailable"
    rows = []
    for symbol, value in raw[weight_column].items():
        weight = normalize_weight(value)
        if weight is not None:
            rows.append({"ticker": str(symbol).upper(), "weight_pct": rounded(weight)})
    return sorted(rows, key=lambda item: item["weight_pct"], reverse=True)[:limit], "available"


def sector_weights_from_funds_data(funds_data: Any) -> tuple[list[dict[str, Any]], str]:
    try:
        raw = getattr(funds_data, "sector_weightings", None)
    except Exception:
        return [], "unavailable"
    if isinstance(raw, pd.DataFrame):
        if raw.empty:
            return [], "unavailable"
        values: Iterable[tuple[Any, Any]] = raw.iloc[:, 0].items()
    elif isinstance(raw, dict):
        values = raw.items()
    elif isinstance(raw, list) and raw and isinstance(raw[0], dict):
        values = raw[0].items()
    else:
        return [], "unavailable"
    rows = []
    for sector, value in values:
        weight = normalize_weight(value)
        if weight is not None:
            rows.append({"sector": str(sector), "weight_pct": rounded(weight)})
    status = "available" if rows else "unavailable"
    return sorted(rows, key=lambda item: item["weight_pct"], reverse=True), status


def dividends_from_ticker(ticker: Any) -> pd.Series:
    try:
        raw = getattr(ticker, "dividends", None)
    except Exception:
        return pd.Series(dtype=float)
    if not isinstance(raw, pd.Series) or raw.empty:
        return pd.Series(dtype=float)
    values = pd.to_numeric(raw, errors="coerce").dropna()
    values.index = pd.to_datetime(values.index).tz_localize(None)
    return values.sort_index()


def quality_summary(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    complete = sum(1 for item in evidence if item.get("status") == "available")
    status = (
        "available"
        if complete == len(evidence) and evidence
        else "partial" if complete else "limited"
    )
    return {
        "status": status,
        "available_sources": complete,
        "total_sources": len(evidence),
    }


def target_weights(scored: list[tuple[str, float]]) -> list[dict[str, Any]]:
    total = sum(score for _, score in scored)
    if total <= 0:
        return []
    rows = []
    for index, (ticker, score) in enumerate(scored):
        weight = 100 - sum(row["target_weight_pct"] for row in rows)
        if index < len(scored) - 1:
            weight = rounded(score / total * 100) or 0.0
        rows.append({"ticker": ticker, "target_weight_pct": rounded(weight)})
    return rows
