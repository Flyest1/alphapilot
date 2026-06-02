from types import SimpleNamespace

import pandas as pd
from fastapi.testclient import TestClient

from app.db.supabase_client import InMemoryRepository
from app.main import create_app

AUTH = {"Authorization": "Bearer test-api-token"}


class FakeBenchmarkMarketData:
    def fetch_usd_krw_rate(self, fallback=None):
        return 1400

    def fetch_major_indices(self, report_type, lookback_days, stale_data_business_days):
        labels = ["KOSPI", "KOSDAQ"] if report_type == "domestic" else ["S&P 500", "NASDAQ"]
        return {
            label: SimpleNamespace(
                dataframe=pd.DataFrame(
                    {"close": [100, 102]},
                    index=pd.date_range("2026-05-20", periods=2, freq="B"),
                )
            )
            for label in labels
        }

    def fetch_price_history(self, market, ticker, lookback_days=180, stale_data_business_days=2):
        return SimpleNamespace(
            is_stale=False,
            current_price=100,
            dataframe=pd.DataFrame(
                {"close": [100, 102]},
                index=pd.date_range("2026-05-20", periods=2, freq="B"),
            ),
        )


def test_portfolio_snapshot_endpoint_creates_manual_snapshot():
    repo = InMemoryRepository()
    repo.create_asset(
        {
            "market": "CASH",
            "ticker": "KRW",
            "name": "Cash",
            "quantity": 1000,
            "avg_price": 1,
            "currency": "KRW",
        }
    )
    app = create_app(repository=repo)
    app.state.market_data_service = FakeBenchmarkMarketData()
    test_client = TestClient(app)

    response = test_client.post("/api/portfolio/snapshot", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total_market_value"] == 1000
    assert body["snapshot"]["report_type"] == "manual"
    assert repo.list_portfolio_snapshots()[0]["total_market_value"] == 1000


def test_portfolio_benchmark_returns_endpoint_uses_existing_providers():
    repo = InMemoryRepository()
    repo.create_portfolio_snapshot(
        {"snapshot_date": "2026-05-20", "report_type": "manual", "total_market_value": 1000}
    )
    repo.create_portfolio_snapshot(
        {"snapshot_date": "2026-05-21", "report_type": "manual", "total_market_value": 1100}
    )
    app = create_app(repository=repo)
    app.state.market_data_service = FakeBenchmarkMarketData()
    test_client = TestClient(app)

    response = test_client.get("/api/portfolio/benchmark-returns?days=7", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    keys = {row["key"] for row in body["series"]}
    assert {"kospi", "kosdaq", "sp500", "nasdaq", "actual_portfolio"}.issubset(keys)
