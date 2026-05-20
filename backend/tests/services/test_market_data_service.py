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

    def get_market_ohlcv_by_date(self, start, end, ticker):
        self.calls.append((start, end, ticker))
        return self.frame

    def get_nearest_business_day_in_a_week(self, date_text):
        return date_text


class FailingKRProvider:
    def get_market_ohlcv_by_date(self, _start, _end, _ticker):
        raise RuntimeError("provider failed")

    def get_nearest_business_day_in_a_week(self, date_text):
        return date_text


class FakeTicker:
    def __init__(self, frame):
        self.frame = frame

    def history(self, **_kwargs):
        return self.frame


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
