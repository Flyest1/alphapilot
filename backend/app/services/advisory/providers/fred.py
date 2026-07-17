from __future__ import annotations

import json
import os
import socket
import ssl
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.utils.logging import log_external_failure

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_HOST = "api.stlouisfed.org"
FRED_PROVIDER_NAME = "fred"
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_ATTEMPTS = 3
MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 0.25
MAX_BACKOFF_SECONDS = 2.0
DEFAULT_CACHE_TTL_SECONDS = 900.0
MAX_CACHE_TTL_SECONDS = 3600.0
SIX_MONTH_LOOKBACK_DAYS = 190
MAX_OBSERVATIONS_PER_SERIES = 500
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class FredSeriesSpec:
    series_id: str
    label: str
    category: str
    units: str
    frequency: str


FRED_SERIES_ALLOWLIST: dict[str, FredSeriesSpec] = {
    "FEDFUNDS": FredSeriesSpec(
        "FEDFUNDS",
        "Effective Federal Funds Rate",
        "policy_rate",
        "Percent",
        "Monthly",
    ),
    "DGS2": FredSeriesSpec(
        "DGS2",
        "Market Yield on U.S. Treasury Securities at 2-Year Constant Maturity",
        "treasury_yield",
        "Percent",
        "Daily",
    ),
    "DGS10": FredSeriesSpec(
        "DGS10",
        "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity",
        "treasury_yield",
        "Percent",
        "Daily",
    ),
    "T10Y2Y": FredSeriesSpec(
        "T10Y2Y",
        "10-Year Treasury Constant Maturity Minus 2-Year Treasury Constant Maturity",
        "treasury_yield_curve",
        "Percentage Points",
        "Daily",
    ),
    "CPIAUCSL": FredSeriesSpec(
        "CPIAUCSL",
        "Consumer Price Index for All Urban Consumers: All Items",
        "inflation",
        "Index 1982-1984=100",
        "Monthly",
    ),
    "CPILFESL": FredSeriesSpec(
        "CPILFESL",
        "Consumer Price Index for All Urban Consumers: All Items Less Food and Energy",
        "inflation",
        "Index 1982-1984=100",
        "Monthly",
    ),
    "UNRATE": FredSeriesSpec(
        "UNRATE",
        "Unemployment Rate",
        "labor_market",
        "Percent",
        "Monthly",
    ),
    "INDPRO": FredSeriesSpec(
        "INDPRO",
        "Industrial Production: Total Index",
        "industrial_activity",
        "Index 2017=100",
        "Monthly",
    ),
    "PAYEMS": FredSeriesSpec(
        "PAYEMS",
        "All Employees, Total Nonfarm",
        "labor_market",
        "Thousands of Persons",
        "Monthly",
    ),
    "RSXFS": FredSeriesSpec(
        "RSXFS",
        "Advance Retail Sales: Retail and Food Services",
        "consumer_activity",
        "Millions of Dollars",
        "Monthly",
    ),
}


class FredMacroProvider:
    """Read-only, bounded FRED macro-data provider for advisory research."""

    def __init__(
        self,
        api_key: str | None = None,
        opener: Callable[..., Any] | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
        sleep: Callable[[float], None] | None = None,
        now_provider: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        if not 0 < timeout_seconds <= MAX_TIMEOUT_SECONDS:
            raise ValueError(f"timeout_seconds must be between 0 and {MAX_TIMEOUT_SECONDS}")
        if not 1 <= max_attempts <= MAX_ATTEMPTS:
            raise ValueError(f"max_attempts must be between 1 and {MAX_ATTEMPTS}")
        if not 0 <= backoff_seconds <= MAX_BACKOFF_SECONDS:
            raise ValueError(f"backoff_seconds must be between 0 and {MAX_BACKOFF_SECONDS}")
        if not 0 < cache_ttl_seconds <= MAX_CACHE_TTL_SECONDS:
            raise ValueError(f"cache_ttl_seconds must be between 0 and {MAX_CACHE_TTL_SECONDS}")

        self.api_key = (api_key if api_key is not None else os.getenv("FRED_API_KEY", "")).strip()
        self.opener = opener or build_opener(_NoRedirectHandler()).open
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.sleep = sleep or time.sleep
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic or time.monotonic
        self._cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
        self._cache_lock = Lock()

    def fetch_six_month_context(self, series_ids: Iterable[str] | None = None) -> dict[str, Any]:
        """Return only allowlisted FRED observations for the latest six-month research window."""
        end_date = self._now().date()
        return self.fetch_context(
            series_ids=series_ids,
            observation_start=end_date - timedelta(days=SIX_MONTH_LOOKBACK_DAYS),
            observation_end=end_date,
        )

    def fetch_context(
        self,
        series_ids: Iterable[str] | None = None,
        observation_start: date | datetime | str | None = None,
        observation_end: date | datetime | str | None = None,
    ) -> dict[str, Any]:
        """Fetch allowlisted raw observations and preserve their FRED vintage metadata."""
        retrieved_at = self._now().isoformat()
        start_date = self._normalize_date(observation_start)
        end_date = self._normalize_date(observation_end)
        if start_date is None and end_date is None:
            end_date = self._now().date()
            start_date = end_date - timedelta(days=400)
        if start_date and end_date and start_date > end_date:
            raise ValueError("observation_start must not be after observation_end")

        selected_ids = self._select_series_ids(series_ids)
        if not self.api_key:
            return self._unavailable_result(
                retrieved_at,
                selected_ids,
                reason="not_configured",
            )

        series: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for series_id in selected_ids:
            try:
                result = self._fetch_series(series_id, start_date, end_date, retrieved_at)
            except Exception as exc:
                failure = self._failure_detail(series_id, exc)
                failures.append(failure)
                log_external_failure(
                    FRED_PROVIDER_NAME,
                    RuntimeError(f"FRED request failed: {failure['reason']}"),
                    {"operation": "fetch_macro_series", "series_id": series_id},
                )
                continue
            if result is None:
                failures.append({"series_id": series_id, "reason": "no_data"})
            else:
                series.append(result)

        status = self._result_status(series, failures)
        return {
            "provider": FRED_PROVIDER_NAME,
            "status": status,
            "retrieved_at": retrieved_at,
            "observation_start": start_date.isoformat() if start_date else None,
            "observation_end": end_date.isoformat() if end_date else None,
            "requested_series_ids": selected_ids,
            "series": series,
            "failures": failures,
            "limitations": self._limitations(status, failures),
        }

    def _fetch_series(
        self,
        series_id: str,
        observation_start: date | None,
        observation_end: date | None,
        retrieved_at: str,
    ) -> dict[str, Any] | None:
        cache_key = (
            series_id,
            observation_start.isoformat() if observation_start else "",
            observation_end.isoformat() if observation_end else "",
        )
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        payload = self._request_observations(series_id, observation_start, observation_end)
        result = self._normalize_series(series_id, payload, retrieved_at)
        if result is not None:
            self._put_cached(cache_key, result)
        return result

    def _request_observations(
        self,
        series_id: str,
        observation_start: date | None,
        observation_end: date | None,
    ) -> dict[str, Any]:
        params = {
            "series_id": series_id,
            "api_key": self.api_key,
            "file_type": "json",
            "sort_order": "asc",
            "limit": str(MAX_OBSERVATIONS_PER_SERIES),
        }
        if observation_start:
            params["observation_start"] = observation_start.isoformat()
        if observation_end:
            params["observation_end"] = observation_end.isoformat()
        request = Request(
            f"{FRED_OBSERVATIONS_URL}?{urlencode(params)}",
            headers={
                "Accept": "application/json",
                "User-Agent": "AlphaPilot/0.1 advisory-research",
            },
        )
        for attempt in range(self.max_attempts):
            try:
                with self.opener(request, timeout=self.timeout_seconds) as response:
                    response_url = getattr(response, "geturl", lambda: request.full_url)()
                    self._validate_response_url(response_url)
                    try:
                        raw = response.read(MAX_RESPONSE_BYTES + 1)
                    except TypeError:
                        raw = response.read()
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise ValueError("FRED response exceeded the configured size limit")
                    payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("FRED payload must be an object")
                if payload.get("error_code"):
                    raise ValueError("FRED returned an API error")
                return payload
            except Exception as exc:
                if attempt + 1 >= self.max_attempts or not self._is_retryable(exc):
                    raise
                self.sleep(min(self.backoff_seconds * (2**attempt), MAX_BACKOFF_SECONDS))
        raise RuntimeError("FRED retry loop exhausted")

    @staticmethod
    def _validate_response_url(url: str) -> None:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != FRED_HOST
            or parsed.username
            or parsed.port not in (None, 443)
            or parsed.path != "/fred/series/observations"
        ):
            raise ValueError("FRED response URL is not allowlisted")

    def _normalize_series(
        self,
        series_id: str,
        payload: dict[str, Any],
        retrieved_at: str,
    ) -> dict[str, Any] | None:
        rows = payload.get("observations")
        if not isinstance(rows, list):
            raise ValueError("FRED observations must be a list")

        observations = [
            normalized
            for row in rows
            if (normalized := self._normalize_observation(row)) is not None
        ]
        if not observations:
            return None
        spec = FRED_SERIES_ALLOWLIST[series_id]
        return {
            "series_id": spec.series_id,
            "label": spec.label,
            "category": spec.category,
            "units": spec.units,
            "frequency": spec.frequency,
            "provider": FRED_PROVIDER_NAME,
            "retrieved_at": retrieved_at,
            "observations": observations,
            "realtime_vintage": {
                "realtime_start": payload.get("realtime_start"),
                "realtime_end": payload.get("realtime_end"),
                "observation_start": payload.get("observation_start"),
                "observation_end": payload.get("observation_end"),
            },
        }

    @staticmethod
    def _normalize_observation(row: Any) -> dict[str, Any] | None:
        if not isinstance(row, dict):
            return None
        observation_date = row.get("date")
        value = row.get("value")
        if not isinstance(observation_date, str) or not observation_date.strip():
            return None
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None
        if not isfinite(numeric_value):
            return None
        return {
            "observation_date": observation_date,
            "value": numeric_value,
            "realtime_start": row.get("realtime_start"),
            "realtime_end": row.get("realtime_end"),
        }

    def _get_cached(self, cache_key: tuple[str, str, str]) -> dict[str, Any] | None:
        with self._cache_lock:
            item = self._cache.get(cache_key)
            if item is None:
                return None
            expires_at, result = item
            if self.monotonic() >= expires_at:
                self._cache.pop(cache_key, None)
                return None
            return result.copy()

    def _put_cached(self, cache_key: tuple[str, str, str], result: dict[str, Any]) -> None:
        with self._cache_lock:
            self._cache[cache_key] = (self.monotonic() + self.cache_ttl_seconds, result.copy())

    @staticmethod
    def _select_series_ids(series_ids: Iterable[str] | None) -> list[str]:
        if series_ids is None:
            return list(FRED_SERIES_ALLOWLIST)
        selected = list(dict.fromkeys(str(series_id).strip().upper() for series_id in series_ids))
        unknown = [series_id for series_id in selected if series_id not in FRED_SERIES_ALLOWLIST]
        if unknown:
            raise ValueError(f"FRED series is not allowlisted: {', '.join(unknown)}")
        return selected

    def _now(self) -> datetime:
        current = self.now_provider()
        return (
            current.replace(tzinfo=timezone.utc)
            if current.tzinfo is None
            else current.astimezone(timezone.utc)
        )

    @staticmethod
    def _normalize_date(value: date | datetime | str | None) -> date | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            return date.fromisoformat(value)
        raise ValueError("observation dates must be date, datetime, ISO date strings, or None")

    @staticmethod
    def _is_retryable(exc: BaseException) -> bool:
        if isinstance(exc, HTTPError):
            return exc.code in RETRYABLE_HTTP_STATUS
        if isinstance(exc, ssl.SSLCertVerificationError):
            return False
        if isinstance(exc, URLError) and isinstance(exc.reason, ssl.SSLCertVerificationError):
            return False
        if isinstance(exc, URLError):
            return True
        return isinstance(exc, (socket.timeout, TimeoutError, ConnectionError, OSError))

    @classmethod
    def _failure_detail(cls, series_id: str, exc: BaseException) -> dict[str, str]:
        if isinstance(exc, HTTPError):
            return {"series_id": series_id, "reason": "http", "http_status": str(exc.code)}
        if isinstance(exc, (socket.timeout, TimeoutError)):
            return {"series_id": series_id, "reason": "timeout"}
        if isinstance(exc, URLError):
            return {"series_id": series_id, "reason": "network"}
        if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError, ValueError)):
            return {"series_id": series_id, "reason": "invalid_response"}
        return {"series_id": series_id, "reason": "unavailable"}

    @staticmethod
    def _result_status(series: list[dict[str, Any]], failures: list[dict[str, str]]) -> str:
        if series:
            return "partial" if failures else "ok"
        if failures and all(failure["reason"] == "no_data" for failure in failures):
            return "empty"
        return "unavailable"

    @staticmethod
    def _limitations(status: str, failures: list[dict[str, str]]) -> list[str]:
        if status == "ok":
            return []
        if status == "empty":
            return ["FRED returned no usable observations for the requested series and period."]
        if status == "partial":
            return ["Some requested FRED series were unavailable or had no usable observations."]
        if any(failure["reason"] == "not_configured" for failure in failures):
            return ["FRED_API_KEY is not configured on the backend."]
        return ["FRED macro data is unavailable; no macro values were inferred."]

    @staticmethod
    def _unavailable_result(
        retrieved_at: str,
        requested_series_ids: list[str],
        reason: str,
    ) -> dict[str, Any]:
        return {
            "provider": FRED_PROVIDER_NAME,
            "status": "unavailable",
            "retrieved_at": retrieved_at,
            "observation_start": None,
            "observation_end": None,
            "requested_series_ids": requested_series_ids,
            "series": [],
            "failures": [{"reason": reason}],
            "limitations": ["FRED_API_KEY is not configured on the backend."],
        }
