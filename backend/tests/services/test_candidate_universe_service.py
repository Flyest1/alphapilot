from datetime import datetime, timezone

import pandas as pd

from app.db.supabase_client import InMemoryRepository
from app.services.candidate_universe_service import CandidateUniverseService


class FakeKR:
    def get_nearest_business_day_in_a_week(self, value):
        return value

    def get_market_cap_by_ticker(self, _date, market="ALL"):
        assert market == "ALL"
        return pd.DataFrame({"시가총액": [300, 200, 100]}, index=["005930", "000660", "035420"])

    def get_market_ticker_name(self, ticker):
        return {"005930": "삼성전자", "000660": "SK하이닉스", "035420": "NAVER"}[ticker]


class FakeTicker:
    def __init__(self, ticker):
        self.info = {"longName": f"{ticker} fund"}


class FakeYF:
    def Ticker(self, ticker):
        return FakeTicker(ticker)


def test_refresh_upserts_market_cap_and_major_etf_rows():
    repository = InMemoryRepository()
    service = CandidateUniverseService(
        repository,
        kr_provider=FakeKR(),
        yf_module=FakeYF(),
        now_provider=lambda: datetime(2026, 6, 14, tzinfo=timezone.utc),
    )

    result = service.refresh()

    assert result["domestic_upserted"] == 3
    assert result["global_etf_upserted"] == 10
    domestic = repository.list_candidate_universe("domestic")
    assert [row["ticker"] for row in domestic] == ["005930", "000660", "035420"]
    assert domestic[0]["source"] == "pykrx_market_cap"
