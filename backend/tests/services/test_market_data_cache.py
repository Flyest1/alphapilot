from datetime import datetime, timezone

import pandas as pd

from app.db.supabase_client import InMemoryRepository
from app.services.market_data_service import MarketDataService


class FakeYf:
    def __init__(self):
        self.calls = 0
        index = pd.date_range("2026-06-01", periods=5, freq="B")
        self.frame = pd.DataFrame(
            {
                "Open": [1, 2, 3, 4, 5],
                "High": [2, 3, 4, 5, 6],
                "Low": [0, 1, 2, 3, 4],
                "Close": [1.5, 2.5, 3.5, 4.5, 5.5],
                "Volume": [10, 20, 30, 40, 50],
            },
            index=index,
        )

    def Ticker(self, _symbol):
        self.calls += 1
        fake = self

        class _Ticker:
            def history(self, **_kwargs):
                return fake.frame

        return _Ticker()


def build_service(repo, yf):
    return MarketDataService(
        yf_module=yf,
        now_provider=lambda: datetime(2026, 6, 5, tzinfo=timezone.utc),
        repository=repo,
    )


def test_persistent_cache_avoids_refetch_after_cold_start():
    repo = InMemoryRepository()
    yf = FakeYf()

    first = build_service(repo, yf).fetch_price_history("US", "AAPL")
    assert yf.calls == 1
    assert not first.is_stale

    # 새 서비스 인스턴스 = 콜드스타트 후 프로세스. 같은 날 조회는 영속 캐시를 사용한다.
    second = build_service(repo, yf).fetch_price_history("US", "AAPL")

    assert yf.calls == 1
    assert second.current_price == first.current_price
    assert second.provider == first.provider
    assert list(second.dataframe.columns) == list(first.dataframe.columns)
    assert len(second.dataframe) == len(first.dataframe)


def test_fetch_works_without_repository():
    yf = FakeYf()
    service = MarketDataService(
        yf_module=yf,
        now_provider=lambda: datetime(2026, 6, 5, tzinfo=timezone.utc),
    )

    result = service.fetch_price_history("US", "AAPL")

    assert result.current_price == 5.5


def test_price_lineage_survives_cache_without_becoming_a_new_observation():
    repo, yf = InMemoryRepository(), FakeYf()
    yf.frame["Adj Close"] = yf.frame["Close"] / 2
    yf.frame["Dividends"] = [0, 0, 1, 0, 0]
    yf.frame["Stock Splits"] = [0, 0, 0, 2, 0]
    first = build_service(repo, yf).fetch_price_history("US", "AAPL")
    second = build_service(repo, yf).fetch_price_history("US", "AAPL")
    assert first.price_lineage == second.price_lineage
    assert first.price_lineage["request_options"]["auto_adjust"] is False
    assert "Dividends" in first.price_lineage["raw_daily_bars"]["columns"]
    assert "Adj Close" in first.price_lineage["raw_daily_bars"]["columns"]
    assert len(first.price_lineage["source_sha256"]) == 64
    assert list(first.dataframe.columns) == ["open", "high", "low", "close", "volume"]
    assert yf.calls == 1


def test_legacy_cache_does_not_invent_price_lineage():
    repo, yf = InMemoryRepository(), FakeYf()
    service = build_service(repo, yf)
    service.fetch_price_history("US", "AAPL")
    key = "US:AAPL:180:2:2026-06-05"
    row = repo.get_market_data_cache(key)
    row["payload"].pop("price_lineage", None)
    repo.upsert_market_data_cache(key, row["payload"])
    result = build_service(repo, yf).fetch_price_history("US", "AAPL")
    assert result.price_lineage == {}
    assert yf.calls == 1


def test_regular_close_elapsed_is_not_finality_certification():
    yf = FakeYf()
    service = MarketDataService(
        yf_module=yf, now_provider=lambda: datetime(2026, 6, 5, 19, tzinfo=timezone.utc)
    )
    early = service.fetch_price_history("US", "AAPL").price_lineage["latest_session"]
    assert early["regular_close_elapsed"] is False
    late = (
        MarketDataService(
            yf_module=yf, now_provider=lambda: datetime(2026, 6, 5, 21, tzinfo=timezone.utc)
        )
        .fetch_price_history("US", "AAPL")
        .price_lineage["latest_session"]
    )
    assert late["regular_close_elapsed"] is True
    assert late["provider_finality_verified"] is False
    assert late["exchange_calendar_verified"] is False
