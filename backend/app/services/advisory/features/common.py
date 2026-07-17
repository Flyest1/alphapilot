from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable, Mapping

import pandas as pd


def now_iso(now_provider: Any | None = None) -> str:
    provider = now_provider or (lambda: datetime.now(timezone.utc))
    value = provider()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def rounded(value: Any, digits: int = 2) -> float | None:
    number = finite_float(value)
    return round(number, digits) if number is not None else None


def percent_change(current: Any, previous: Any) -> float | None:
    current_value = finite_float(current)
    previous_value = finite_float(previous)
    if current_value is None or previous_value in {None, 0.0}:
        return None
    return round((current_value / previous_value - 1) * 100, 2)


def frame_columns(frame: Any) -> list[Any]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    try:
        return sorted(frame.columns, reverse=True)
    except TypeError:
        return list(frame.columns)


def statement_values(frame: Any, labels: Iterable[str]) -> tuple[float | None, float | None]:
    columns = frame_columns(frame)
    if not columns:
        return None, None
    label_lookup = {str(index).casefold(): index for index in frame.index}
    row_key = next(
        (
            label_lookup.get(label.casefold())
            for label in labels
            if label.casefold() in label_lookup
        ),
        None,
    )
    if row_key is None:
        return None, None
    latest = finite_float(frame.loc[row_key, columns[0]])
    previous = finite_float(frame.loc[row_key, columns[1]]) if len(columns) > 1 else None
    return latest, previous


def safe_attribute(target: Any, name: str, default: Any = None) -> Any:
    try:
        value = getattr(target, name)
    except Exception:
        return default
    return default if value is None else value


def ticker_snapshot(yf_module: Any, ticker: str) -> dict[str, Any]:
    instance = yf_module.Ticker(ticker)
    return {
        "ticker": ticker,
        "info": safe_attribute(instance, "info", {}) or {},
        "quarterly_financials": safe_attribute(instance, "quarterly_financials", pd.DataFrame()),
        "quarterly_cashflow": safe_attribute(instance, "quarterly_cashflow", pd.DataFrame()),
        "quarterly_balance_sheet": safe_attribute(
            instance, "quarterly_balance_sheet", pd.DataFrame()
        ),
    }


def close_series(market_data: Any) -> pd.Series:
    frame = getattr(market_data, "dataframe", None)
    if not isinstance(frame, pd.DataFrame) or frame.empty or "close" not in frame:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame["close"], errors="coerce").dropna()


def period_return(market_data: Any, observations: int | None = None) -> float | None:
    closes = close_series(market_data)
    if observations is not None:
        closes = closes.tail(observations)
    if len(closes) < 2 or float(closes.iloc[0]) == 0:
        return None
    return round((float(closes.iloc[-1]) / float(closes.iloc[0]) - 1) * 100, 2)


def price_on_or_after(market_data: Any, date_value: Any) -> float | None:
    closes = close_series(market_data)
    if closes.empty:
        return None
    try:
        target = pd.Timestamp(date_value).tz_localize(None)
    except (TypeError, ValueError):
        return None
    eligible = closes.loc[closes.index >= target]
    return finite_float(eligible.iloc[0]) if not eligible.empty else None


def data_quality(rows: Iterable[Mapping[str, Any]], limitations: list[str]) -> dict[str, Any]:
    row_list = list(rows)
    missing = sorted(
        {
            field
            for row in row_list
            for field, value in row.items()
            if value is None and not field.endswith("_optional")
        }
    )
    status = "fresh"
    if not row_list:
        status = "unavailable"
    elif missing or limitations:
        status = "partial"
    return {
        "status": status,
        "missing_fields": missing,
        "limitations": limitations,
    }


def evidence_item(
    evidence_id: str,
    provider: str,
    title: str,
    as_of: str | None,
    *,
    url: str | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "evidence_id": evidence_id,
        "provider": provider,
        "title": title,
        "as_of": as_of,
        "url": url,
        "limitations": limitations or [],
    }


def valuation_score(info: Mapping[str, Any]) -> float:
    score = 0.0
    trailing_pe = finite_float(info.get("trailingPE"))
    forward_pe = finite_float(info.get("forwardPE"))
    price_to_book = finite_float(info.get("priceToBook"))
    enterprise_to_ebitda = finite_float(info.get("enterpriseToEbitda"))
    if trailing_pe is not None and 0 < trailing_pe <= 20:
        score += 1.0
    if forward_pe is not None and 0 < forward_pe <= 18:
        score += 1.0
    if price_to_book is not None and 0 < price_to_book <= 3:
        score += 1.0
    if enterprise_to_ebitda is not None and 0 < enterprise_to_ebitda <= 12:
        score += 1.0
    return score
