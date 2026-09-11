"""Preserve collection evidence without asserting historical price-basis equivalence."""

import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pandas as pd


def collect_price_lineage(
    raw: pd.DataFrame, provider: str, ticker: str, observed_at: datetime, request_options: dict
) -> dict:
    if raw is None or raw.empty:
        return {}
    columns = [
        key
        for key in (
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
            "Adj Close",
            "Dividends",
            "Stock Splits",
            "Capital Gains",
            "시가",
            "고가",
            "저가",
            "종가",
            "거래량",
        )
        if key in raw
    ]
    if not columns:
        return {}
    # Preserve source session labels, not UTC-converted labels, for daily-bar evidence.
    evidence = raw[columns].copy()
    evidence.index = [pd.Timestamp(stamp).isoformat() for stamp in raw.index]
    encoded = evidence.to_json(orient="split", double_precision=15, force_ascii=False)
    bars = json.loads(encoded)
    canonical = json.dumps(
        bars, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    zone_name = "Asia/Seoul" if provider == "pykrx" else "America/New_York"
    zone = ZoneInfo(zone_name)
    aware_observation = observed_at.tzinfo is not None
    last = pd.Timestamp(raw.index.max())
    day = last.tz_convert(zone).date() if last.tzinfo is not None else last.date()
    close_time = time(15, 30) if provider == "pykrx" else time(16)
    elapsed = None
    if aware_observation:
        elapsed = observed_at.astimezone(zone) >= datetime.combine(day, close_time, zone)
    try:
        package_version = version(provider)
    except PackageNotFoundError:
        package_version = None
    return {
        "version": "price_lineage_v1",
        "provider": provider,
        "provider_version": package_version,
        "provider_symbol": ticker,
        "observed_at": (
            observed_at.astimezone(timezone.utc).isoformat() if aware_observation else None
        ),
        "request_options": request_options,
        "price_basis_verified": False,
        "adjustment_vintage": "not_supplied_by_provider",
        "raw_daily_bars": bars,
        "source_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "source_hash_format": "sorted_compact_json_utf8_precision15",
        "action_columns_present": [
            key for key in ("Dividends", "Stock Splits", "Capital Gains") if key in columns
        ],
        "latest_session": {
            "date": day.isoformat(),
            "timezone": zone_name,
            "regular_close_elapsed": elapsed,
            "exchange_calendar_verified": False,
            "provider_finality_verified": False,
        },
    }
