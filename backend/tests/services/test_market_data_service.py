from datetime import datetime, timezone

import pandas as pd

from app.services.market_data_service import MarketDataService


def history(last_date="2026-05-21"):
    index = pd.date_range("2026-05-15", last_date, freq="B")
    return pd.DataFrame(
        {
            "Open": range(1, len(index) + 1),
            "High": range(2, len(index) + 2),
            "Low": range(0, len(index)),
            "Close": range(10, 10 + len(index)),
            "Volume": range(100, 100 + len(index)),
        },
        index=index,
    )


class FakeKRProvider:
    def __init__(self, frame):
        self.frame = frame
        self.calls = []

    def get_market_ohlcv_by_date(self, start, end, ticker, *, adjusted=True):
        assert adjusted is True
        self.calls.append((start, end, ticker))
        return self.frame

    def get_nearest_business_day_in_a_week(self, date_text):
        return date_text


class FailingKRProvider:
    def get_market_ohlcv_by_date(self, _start, _end, _ticker, **_kwargs):
        raise RuntimeError("provider failed")

    def get_nearest_business_day_in_a_week(self, date_text):
        return date_text


class FakeTicker:
    def __init__(self, frame):
        self.frame = frame

    def history(self, **_kwargs):
        return self.frame

    @property
    def calendar(self):
        return {
            "Earnings Date": [datetime(2026, 6, 1, tzinfo=timezone.utc)],
            "Ex-Dividend Date": datetime(2026, 6, 5, tzinfo=timezone.utc),
        }


class FakeYFinance:
    def __init__(self, frame):
        self.frame = frame
        self.tickers = []

    def Ticker(self, ticker):
        self.tickers.append(ticker)
        return FakeTicker(self.frame)


def test_routes_kr_market_to_pykrx():
    provider = FakeKRProvider(history())
    service = MarketDataService(
        kr_provider=provider,
        now_provider=lambda: datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    result = service.fetch_price_history("KR", "005930")

    assert result.provider == "pykrx"
    assert result.current_price == 14
    assert provider.calls[0][2] == "005930"


def test_standardizes_pykrx_korean_columns():
    frame = history().rename(
        columns={
            "Open": "시가",
            "High": "고가",
            "Low": "저가",
            "Close": "종가",
            "Volume": "거래량",
        }
    )
    provider = FakeKRProvider(frame)
    service = MarketDataService(
        kr_provider=provider,
        now_provider=lambda: datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    result = service.fetch_price_history("KR", "005930")

    assert result.current_price == 14
    assert list(result.dataframe.columns) == ["open", "high", "low", "close", "volume"]


def test_routes_us_market_to_yfinance():
    yf = FakeYFinance(history())
    service = MarketDataService(
        yf_module=yf,
        now_provider=lambda: datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    result = service.fetch_price_history("US", "aapl")

    assert result.provider == "yfinance"
    assert result.current_price == 14
    assert yf.tickers == ["AAPL"]


def test_normalizes_us_ticker_dot_to_dash_for_yfinance():
    yf = FakeYFinance(history())
    service = MarketDataService(yf_module=yf)

    service.fetch_price_history("US", "BRK.B")

    assert yf.tickers == ["BRK-B"]


def test_standardizes_timezone_aware_yfinance_index():
    frame = history()
    frame.index = frame.index.tz_localize("America/New_York")
    yf = FakeYFinance(frame)
    service = MarketDataService(yf_module=yf)

    result = service.fetch_price_history("US", "AAPL")

    assert result.current_price == 14
    assert result.dataframe.index.tz is None


def test_fetches_usd_krw_rate_from_yfinance():
    yf = FakeYFinance(history())
    service = MarketDataService(yf_module=yf)

    rate = service.fetch_usd_krw_rate(fallback=1400)

    assert rate == 14
    assert yf.tickers == ["KRW=X"]


def test_stale_detection_at_exactly_two_business_days_is_not_stale():
    provider = FakeKRProvider(history("2026-05-19"))
    service = MarketDataService(
        kr_provider=provider,
        now_provider=lambda: datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    result = service.fetch_price_history("KR", "005930", stale_data_business_days=2)

    assert result.is_stale is False


def test_provider_failure_returns_stale_result():
    service = MarketDataService(
        kr_provider=FailingKRProvider(),
        now_provider=lambda: datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    result = service.fetch_price_history("KR", "005930")

    assert result.is_stale is True
    assert result.data_quality_note == "pykrx failure; data-limited"


def test_fetch_asset_events_normalizes_yfinance_calendar():
    yf = FakeYFinance(history())
    service = MarketDataService(
        yf_module=yf,
        now_provider=lambda: datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    result = service.fetch_asset_events(
        [{"market": "US", "ticker": "AAPL", "name": "Apple"}],
        days=30,
    )

    assert result["status"] == "ok"
    assert [event["event_type"] for event in result["events"]] == ["earnings", "ex_dividend"]
    assert all(event["provider"] == "yfinance" for event in result["events"])


def test_routes_krx_listed_etf_to_pykrx():
    provider = FakeKRProvider(history())
    yf = FakeYFinance(history())
    service = MarketDataService(
        kr_provider=provider,
        yf_module=yf,
        now_provider=lambda: datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    suffixed = service.fetch_price_history("ETF", "069500.KS")
    bare = service.fetch_price_history("ETF", "069500")
    us_etf = service.fetch_price_history("ETF", "SPY")

    assert suffixed.provider == "pykrx" and not suffixed.is_stale
    assert bare.provider == "pykrx"
    assert [call[2] for call in provider.calls] == ["069500"]  # second call served from cache
    assert us_etf.provider == "yfinance"
    assert yf.tickers == ["SPY"]


def test_duplicate_latest_bar_does_not_break_price_lookup():
    frame = history()
    duplicated = pd.concat([frame, frame.iloc[[-1]].assign(Close=99)])
    service = MarketDataService(
        yf_module=FakeYFinance(duplicated),
        now_provider=lambda: datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    result = service.fetch_price_history("US", "AAPL")

    assert result.current_price == 99
    assert not result.dataframe.index.duplicated().any()
    assert service.fetch_usd_krw_rate(1400) == 99


def test_concurrent_quiet_pykrx_calls_restore_logging():
    import logging
    import threading

    service = MarketDataService(kr_provider=FakeKRProvider(history()))
    original_level = logging.root.manager.disable
    entered = {name: threading.Event() for name in ("a", "b")}
    release = {name: threading.Event() for name in ("a", "b")}

    def blocking_call(name):
        entered[name].set()
        release[name].wait(5)

    threads = {
        name: threading.Thread(target=service._quiet_pykrx_call, args=(blocking_call, name))
        for name in ("a", "b")
    }
    threads["a"].start()
    entered["a"].wait(5)
    threads["b"].start()
    entered["b"].wait(5)
    # The first caller leaves while the second is still inside (the racy order).
    release["a"].set()
    threads["a"].join(5)
    assert logging.root.manager.disable == logging.CRITICAL
    release["b"].set()
    threads["b"].join(5)

    assert logging.root.manager.disable == original_level


def test_staleness_uses_market_local_date():
    # 2026-05-26 01:00 UTC is still Monday 05-25 in New York but Tuesday in Seoul.
    now = datetime(2026, 5, 26, 1, 0, tzinfo=timezone.utc)
    service = MarketDataService(now_provider=lambda: now)
    last_close = datetime(2026, 5, 21)  # Thursday

    assert service._market_today("yfinance").isoformat() == "2026-05-25"
    assert service._market_today("pykrx").isoformat() == "2026-05-26"
    # Fri + Mon = 2 business days in New York -> not stale with the default threshold.
    assert service._is_stale(last_close, "yfinance", 2) is False


def test_transient_market_data_error_predicate():
    from app.services.market_data_service import _is_transient_market_data_error

    class ReadTimeout(Exception):
        pass

    ReadTimeout.__module__ = "requests.exceptions"

    class RateLimited(Exception):
        pass

    RateLimited.__module__ = "yfinance.exceptions"

    assert _is_transient_market_data_error(TimeoutError())
    assert _is_transient_market_data_error(ReadTimeout())
    assert not _is_transient_market_data_error(RateLimited())
    assert not _is_transient_market_data_error(ValueError("bad frame"))
