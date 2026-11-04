from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from io import StringIO
import logging
import threading
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.utils.datetime import parse_iso_datetime
from app.utils.logging import log_external_failure
from app.utils.tickers import is_kr_listed_etf
from app.services.market_price_lineage import collect_price_lineage

KR_YFINANCE_SUFFIXES = (".KS", ".KQ")
MARKET_TIMEZONES = {"pykrx": ZoneInfo("Asia/Seoul"), "yfinance": ZoneInfo("America/New_York")}
_QUIET_LOGGING_LOCK = threading.Lock()
_quiet_logging_depth = 0
_quiet_logging_saved_level = logging.NOTSET


_TRANSIENT_HTTP_LIBRARY_PREFIXES = ("requests", "urllib3", "curl_cffi", "httpx")


def _is_transient_market_data_error(exc: BaseException) -> bool:
    """Retry network-level failures from the HTTP stacks used by yfinance/pykrx.

    Their connection/timeout exceptions do not subclass the builtin ConnectionError or
    TimeoutError, so a builtin-only filter never retried. Rate limits and parse errors are
    not retried.
    """
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    for exc_type in type(exc).__mro__:
        name = exc_type.__name__
        if exc_type.__module__.startswith(_TRANSIENT_HTTP_LIBRARY_PREFIXES) and (
            "Timeout" in name or name in {"ConnectionError", "ConnectError", "ProtocolError"}
        ):
            return True
    return False


@contextmanager
def _quiet_logging() -> Iterator[None]:
    """Silence pykrx's root-logger noise without racing concurrent fetch threads.

    ``logging.disable`` is process-global; a save/restore per call lets overlapping threads
    restore each other's CRITICAL level and switch logging off permanently. A shared depth
    counter restores the original level only when the last caller leaves.
    """
    global _quiet_logging_depth, _quiet_logging_saved_level
    with _QUIET_LOGGING_LOCK:
        if _quiet_logging_depth == 0:
            _quiet_logging_saved_level = logging.root.manager.disable
            logging.disable(logging.CRITICAL)
        _quiet_logging_depth += 1
    try:
        yield
    finally:
        with _QUIET_LOGGING_LOCK:
            _quiet_logging_depth -= 1
            if _quiet_logging_depth == 0:
                logging.disable(_quiet_logging_saved_level)


@dataclass
class MarketDataResult:
    dataframe: pd.DataFrame
    last_trading_date: datetime | None
    is_stale: bool
    provider: str
    data_quality_note: str
    current_price: float | None = None
    price_lineage: dict[str, Any] = field(default_factory=dict)


class MarketDataService:
    def __init__(
        self,
        kr_provider: Any | None = None,
        yf_module: Any | None = None,
        now_provider: Any | None = None,
        repository: Any | None = None,
    ) -> None:
        self.kr_provider = kr_provider
        self.yf_module = yf_module
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        # repository가 주어지면 일중 캐시를 Supabase market_data_cache 테이블에 영속화해
        # 콜드스타트 직후 외부 시세 재호출 폭주를 막는다.
        self.repository = repository
        self._price_cache: dict[tuple[str, str, int, int, str], MarketDataResult] = {}
        self._sector_cache: dict[tuple[str, str], str | None] = {}
        self._event_cache: dict[tuple[str, int, str], dict[str, Any]] = {}

    def fetch_price_history(
        self,
        market: str,
        ticker: str,
        lookback_days: int = 180,
        stale_data_business_days: int = 2,
    ) -> MarketDataResult:
        normalized_market = market.upper()
        if normalized_market == "CASH":
            return MarketDataResult(
                dataframe=pd.DataFrame(),
                last_trading_date=None,
                is_stale=False,
                provider="cash",
                data_quality_note="cash asset; no market data fetch",
                current_price=None,
            )

        price_market = self._price_market(normalized_market, ticker)
        normalized_ticker = self.normalize_ticker(price_market, ticker)
        cache_key = (
            normalized_market,
            normalized_ticker,
            lookback_days,
            stale_data_business_days,
            self.now_provider().date().isoformat(),
        )
        if cache_key in self._price_cache:
            return self._price_cache[cache_key]

        persisted = self._read_persistent_cache(cache_key)
        if persisted is not None:
            self._price_cache[cache_key] = persisted
            return persisted

        provider = self._provider_name(price_market, normalized_ticker)
        try:
            if provider == "pykrx":
                raw = self._fetch_kr_with_retry(normalized_ticker, lookback_days)
            else:
                raw = self._fetch_us_with_retry(normalized_ticker, lookback_days)
            result = self._result_from_frame(
                raw, provider, stale_data_business_days, normalized_ticker
            )
            result.price_lineage = collect_price_lineage(
                raw,
                provider,
                normalized_ticker,
                self.now_provider(),
                (
                    {"adjusted": True}
                    if provider == "pykrx"
                    else {"auto_adjust": False, "actions": True, "repair": False, "prepost": False}
                ),
            )
            self._price_cache[cache_key] = result
            self._write_persistent_cache(cache_key, result)
            return result
        except Exception as exc:
            log_external_failure(
                provider,
                exc,
                {"operation": "fetch_price_history", "market": market, "ticker": ticker},
            )
            return MarketDataResult(
                dataframe=pd.DataFrame(),
                last_trading_date=None,
                is_stale=True,
                provider=provider,
                data_quality_note=f"{provider} failure; data-limited",
                current_price=None,
            )

    def fetch_major_indices(
        self,
        report_type: str,
        lookback_days: int = 180,
        stale_data_business_days: int = 2,
    ) -> dict[str, MarketDataResult]:
        if report_type == "domestic":
            return {
                "KOSPI": self._fetch_kr_index("1001", lookback_days, stale_data_business_days),
                "KOSDAQ": self._fetch_kr_index("2001", lookback_days, stale_data_business_days),
            }
        return {
            "S&P 500": self.fetch_price_history(
                "US", "^GSPC", lookback_days, stale_data_business_days
            ),
            "NASDAQ": self.fetch_price_history(
                "US", "^IXIC", lookback_days, stale_data_business_days
            ),
        }

    def fetch_usd_krw_rate(self, fallback: float | None = None) -> float | None:
        try:
            raw = self._fetch_usd_krw_with_retry()
            frame = self._standardize_frame(raw)
            if frame.empty or "close" not in frame:
                return fallback
            return float(frame["close"].iloc[-1])
        except Exception as exc:
            log_external_failure(
                "yfinance",
                exc,
                {"operation": "fetch_usd_krw_rate", "ticker": "KRW=X"},
            )
            return fallback

    def fetch_sector(self, market: str, ticker: str) -> str | None:
        """yfinance info 기반 섹터 조회 (Phase 4-3 노출 분석용).

        KR 종목은 .KS → .KQ 순서로 yfinance 심볼을 시도한다. 실패하면 None.
        """
        normalized_market = market.upper()
        if normalized_market == "CASH":
            return None
        price_market = self._price_market(normalized_market, ticker)
        normalized_ticker = self.normalize_ticker(price_market, ticker)
        cache_key = (normalized_market, normalized_ticker)
        if cache_key in self._sector_cache:
            return self._sector_cache[cache_key]

        symbols = self._yfinance_symbols(price_market, normalized_ticker)
        sector: str | None = None
        for symbol in symbols:
            try:
                info = self._yf_module().Ticker(symbol).info or {}
            except Exception as exc:
                log_external_failure(
                    "yfinance",
                    exc,
                    {"operation": "fetch_sector", "ticker": symbol},
                )
                continue
            # 개별 주식은 sector, ETF는 category가 분류 정보를 담는다.
            sector = info.get("sector") or info.get("category")
            if sector:
                break
        self._sector_cache[cache_key] = sector
        return sector

    def fetch_asset_events(
        self,
        assets: list[dict[str, Any]],
        days: int = 60,
    ) -> dict[str, Any]:
        """yfinance calendar 범위에서 보유 자산의 향후 실적/배당 일정을 수집한다."""
        cache_key = (
            ",".join(sorted(str(asset.get("ticker") or "") for asset in assets)),
            days,
            self.now_provider().date().isoformat(),
        )
        if cache_key in self._event_cache:
            return self._event_cache[cache_key]
        now = self.now_provider()
        end = now + timedelta(days=days)
        events = []
        for asset in assets:
            if asset.get("market") == "CASH" or not asset.get("ticker"):
                continue
            price_market = self._price_market(
                str(asset.get("market") or "US").upper(), str(asset["ticker"])
            )
            normalized_ticker = self.normalize_ticker(price_market, str(asset["ticker"]))
            symbols = self._yfinance_symbols(price_market, normalized_ticker)
            calendar = None
            for symbol in symbols:
                try:
                    calendar = self._yf_module().Ticker(symbol).calendar
                except Exception as exc:
                    log_external_failure(
                        "yfinance",
                        exc,
                        {"operation": "fetch_asset_calendar", "ticker": symbol},
                    )
                    continue
                if calendar is not None:
                    break
            for event_type, label, date_value in self._calendar_events(calendar):
                parsed = parse_iso_datetime(date_value)
                if parsed is None:
                    continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if parsed < now or parsed > end:
                    continue
                events.append(
                    {
                        "ticker": asset["ticker"],
                        "name": asset.get("name") or asset["ticker"],
                        "event_type": event_type,
                        "label": label,
                        "date": parsed.isoformat(),
                        "provider": "yfinance",
                    }
                )
        result = {
            "provider": "yfinance",
            "status": "ok" if events else "empty",
            "events": sorted(events, key=lambda row: row["date"]),
            "window_days": days,
        }
        self._event_cache[cache_key] = result
        return result

    def _calendar_events(self, calendar: Any) -> list[tuple[str, str, Any]]:
        if calendar is None:
            return []
        if isinstance(calendar, pd.DataFrame):
            if calendar.empty:
                return []
            values = calendar.iloc[:, 0].to_dict()
        elif isinstance(calendar, dict):
            values = calendar
        else:
            return []
        mappings = {
            "Earnings Date": ("earnings", "실적 발표"),
            "EarningsDate": ("earnings", "실적 발표"),
            "Ex-Dividend Date": ("ex_dividend", "배당락"),
            "ExDividendDate": ("ex_dividend", "배당락"),
            "Dividend Date": ("dividend", "배당 지급"),
            "DividendDate": ("dividend", "배당 지급"),
        }
        events = []
        for key, raw_value in values.items():
            mapping = mappings.get(str(key))
            if mapping is None:
                continue
            date_values = raw_value if isinstance(raw_value, (list, tuple)) else [raw_value]
            for value in date_values:
                events.append((mapping[0], mapping[1], value))
        return events

    def _provider_name(self, market: str, ticker: str) -> str:
        upper_ticker = ticker.upper()
        if market == "KR" or upper_ticker.endswith(KR_YFINANCE_SUFFIXES):
            return "pykrx"
        return "yfinance"

    def _price_market(self, market: str, ticker: str) -> str:
        """Route KRX-listed ETFs (e.g. 069500 or 069500.KS) to the KR provider.

        Normalizing first would turn 069500.KS into 069500-KS and send it to yfinance.
        """
        return "KR" if is_kr_listed_etf(market, ticker) else market

    def _yfinance_symbols(self, market: str, normalized_ticker: str) -> list[str]:
        if market == "KR":
            return [f"{normalized_ticker}{suffix}" for suffix in KR_YFINANCE_SUFFIXES]
        return [normalized_ticker]

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(_is_transient_market_data_error),
        reraise=True,
    )
    def _fetch_kr_with_retry(self, ticker: str, lookback_days: int) -> pd.DataFrame:
        provider = self._kr_provider()
        end = self.now_provider().date()
        start = end - timedelta(days=lookback_days * 2)
        normalized = self.normalize_ticker("KR", ticker)
        return self._quiet_pykrx_call(
            provider.get_market_ohlcv_by_date,
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
            normalized,
            adjusted=True,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(_is_transient_market_data_error),
        reraise=True,
    )
    def _fetch_us_with_retry(self, ticker: str, lookback_days: int) -> pd.DataFrame:
        yf_module = self._yf_module()
        normalized = self.normalize_ticker("US", ticker)
        return yf_module.Ticker(normalized).history(
            period=f"{lookback_days}d", auto_adjust=False, actions=True, repair=False, prepost=False
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception(_is_transient_market_data_error),
        reraise=True,
    )
    def _fetch_usd_krw_with_retry(self) -> pd.DataFrame:
        yf_module = self._yf_module()
        return yf_module.Ticker("KRW=X").history(period="5d", auto_adjust=False)

    def _fetch_kr_index(
        self,
        index_code: str,
        lookback_days: int,
        stale_data_business_days: int,
    ) -> MarketDataResult:
        try:
            provider = self._kr_provider()
            end = self.now_provider().date()
            start = end - timedelta(days=lookback_days * 2)
            raw = self._quiet_pykrx_call(
                provider.get_index_ohlcv_by_date,
                start.strftime("%Y%m%d"),
                end.strftime("%Y%m%d"),
                index_code,
            )
            return self._result_from_frame(raw, "pykrx", stale_data_business_days, index_code)
        except Exception as exc:
            log_external_failure(
                "pykrx",
                exc,
                {"operation": "fetch_kr_index", "index_code": index_code},
            )
            return MarketDataResult(
                dataframe=pd.DataFrame(),
                last_trading_date=None,
                is_stale=True,
                provider="pykrx",
                data_quality_note="pykrx index failure; data-limited",
            )

    def _persistent_cache_key(self, cache_key: tuple[str, str, int, int, str]) -> str:
        return ":".join(str(part) for part in cache_key)

    def _read_persistent_cache(
        self, cache_key: tuple[str, str, int, int, str]
    ) -> MarketDataResult | None:
        if self.repository is None:
            return None
        try:
            row = self.repository.get_market_data_cache(self._persistent_cache_key(cache_key))
        except Exception as exc:
            log_external_failure("market_data_cache", exc, {"operation": "read"})
            return None
        payload = (row or {}).get("payload")
        if not payload:
            return None
        try:
            frame = pd.read_json(StringIO(payload["frame"]), orient="split")
            frame.index = pd.to_datetime(frame.index)
            return MarketDataResult(
                dataframe=frame,
                last_trading_date=parse_iso_datetime(payload.get("last_trading_date")),
                is_stale=bool(payload.get("is_stale")),
                provider=str(payload.get("provider") or "cache"),
                data_quality_note=str(payload.get("data_quality_note") or "ok"),
                current_price=payload.get("current_price"),
                price_lineage=(
                    deepcopy(payload.get("price_lineage"))
                    if isinstance(payload.get("price_lineage"), dict)
                    else {}
                ),
            )
        except Exception as exc:
            log_external_failure("market_data_cache", exc, {"operation": "deserialize"})
            return None

    def _write_persistent_cache(
        self,
        cache_key: tuple[str, str, int, int, str],
        result: MarketDataResult,
    ) -> None:
        if self.repository is None or result.dataframe.empty:
            return
        try:
            payload = {
                "frame": result.dataframe.to_json(orient="split", date_format="iso"),
                "last_trading_date": (
                    result.last_trading_date.isoformat() if result.last_trading_date else None
                ),
                "is_stale": result.is_stale,
                "provider": result.provider,
                "data_quality_note": result.data_quality_note,
                "current_price": result.current_price,
                "price_lineage": deepcopy(result.price_lineage),
            }
            self.repository.upsert_market_data_cache(self._persistent_cache_key(cache_key), payload)
        except Exception as exc:
            log_external_failure("market_data_cache", exc, {"operation": "write"})

    def normalize_ticker(self, market: str, ticker: str) -> str:
        upper = ticker.strip().upper()
        if market.upper() == "KR":
            return upper.removesuffix(".KS").removesuffix(".KQ")
        return upper.replace(".", "-")

    def _result_from_frame(
        self,
        raw: pd.DataFrame,
        provider: str,
        stale_data_business_days: int,
        ticker: str,
    ) -> MarketDataResult:
        frame = self._standardize_frame(raw)
        if frame.empty or "close" not in frame:
            return MarketDataResult(
                dataframe=frame,
                last_trading_date=None,
                is_stale=True,
                provider=provider,
                data_quality_note="no market data available; data-limited",
                current_price=None,
            )

        last_timestamp = pd.to_datetime(frame.index.max())
        last_date = last_timestamp.to_pydatetime()
        current_price = float(frame["close"].iloc[-1])
        stale = self._is_stale(last_date, provider, stale_data_business_days)
        note = "stale market data; data-limited" if stale else "ok"
        return MarketDataResult(
            dataframe=frame,
            last_trading_date=last_date,
            is_stale=stale,
            provider=provider,
            data_quality_note=note,
            current_price=current_price,
        )

    def _standardize_frame(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw is None or raw.empty:
            return pd.DataFrame()

        frame = raw.copy()
        index = pd.to_datetime(frame.index)
        frame.index = index.tz_convert(None) if getattr(index, "tz", None) is not None else index
        rename_map = {
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adj_close",
            "Volume": "volume",
            "시가": "open",
            "고가": "high",
            "저가": "low",
            "종가": "close",
            "거래량": "volume",
        }
        frame = frame.rename(columns=rename_map)
        expected = [
            column for column in ("open", "high", "low", "close", "volume") if column in frame
        ]
        if "close" not in expected:
            return pd.DataFrame()
        frame = frame[expected].sort_index()
        # Providers occasionally repeat the latest bar; keep the last copy so scalar lookups and
        # rolling indicators never see duplicated timestamps.
        frame = frame[~frame.index.duplicated(keep="last")]
        for column in expected:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.dropna(subset=["close"])

    def _is_stale(
        self,
        last_trading_date: datetime,
        provider: str,
        stale_data_business_days: int,
    ) -> bool:
        now_date = self._market_today(provider)
        if provider == "pykrx":
            now_date = self._nearest_kr_business_date(now_date)
        last_date = last_trading_date.date()
        if now_date <= last_date:
            return False
        start = np.datetime64(last_date + timedelta(days=1), "D")
        end = np.datetime64(now_date + timedelta(days=1), "D")
        business_days = int(np.busday_count(start, end))
        return business_days > stale_data_business_days

    def _market_today(self, provider: str) -> Any:
        """Today's date in the listing market's time zone (AGENTS.md stale-data rule)."""
        now = self.now_provider()
        market_timezone = MARKET_TIMEZONES.get(provider)
        if market_timezone is None:
            return now.date()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(market_timezone).date()

    def _nearest_kr_business_date(self, current_date: Any) -> Any:
        provider = self._kr_provider()
        if hasattr(provider, "get_nearest_business_day_in_a_week"):
            try:
                nearest = self._quiet_pykrx_call(
                    provider.get_nearest_business_day_in_a_week,
                    current_date.strftime("%Y%m%d"),
                )
                return datetime.strptime(nearest, "%Y%m%d").date()
            except Exception as exc:
                log_external_failure(
                    "pykrx",
                    exc,
                    {"operation": "get_nearest_business_day_in_a_week"},
                )
        return current_date

    def _quiet_pykrx_call(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        with _quiet_logging():
            return func(*args, **kwargs)

    def _kr_provider(self) -> Any:
        if self.kr_provider is None:
            from pykrx import stock

            self.kr_provider = stock
        return self.kr_provider

    def _yf_module(self) -> Any:
        if self.yf_module is None:
            import yfinance as yf

            self.yf_module = yf
        return self.yf_module
