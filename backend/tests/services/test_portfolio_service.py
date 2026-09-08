from types import SimpleNamespace

import pandas as pd

from app.db.supabase_client import InMemoryRepository
from app.services.benchmark_service import BenchmarkService
from app.services.portfolio_service import PortfolioService


class FakeMarketData:
    def fetch_usd_krw_rate(self, fallback=None):
        return fallback

    def fetch_price_history(self, market, ticker):
        prices = {"005930": 120, "AAPL": 80}
        previous = {"005930": 110, "AAPL": 75}
        return SimpleNamespace(
            is_stale=False,
            current_price=prices[ticker],
            dataframe=pd.DataFrame(
                {"close": [previous[ticker], prices[ticker]]},
                index=pd.date_range("2026-05-20", periods=2, freq="B"),
            ),
        )


def test_portfolio_summary_calculates_values_and_returns():
    repo = InMemoryRepository()
    repo.create_asset(
        {
            "market": "KR",
            "ticker": "005930",
            "name": "Samsung",
            "quantity": 2,
            "avg_price": 100,
            "currency": "KRW",
        }
    )
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
    repo.create_asset(
        {
            "market": "US",
            "ticker": "AAPL",
            "name": "Apple",
            "quantity": 1,
            "avg_price": 100,
            "currency": "USD",
        }
    )
    repo.create_asset(
        {
            "market": "CASH",
            "ticker": "USD",
            "name": "USD Cash",
            "quantity": 1,
            "avg_price": 50,
            "currency": "USD",
        }
    )
    repo.upsert_settings({"usd_krw_rate": 1400})

    summary = PortfolioService(repo, FakeMarketData()).get_summary()

    assert summary.total_market_value == 183240
    assert summary.total_cost == 211200
    assert summary.total_profit_loss == -27960
    assert summary.daily_profit_loss == 7020
    assert summary.daily_return_rate == 3.98
    assert summary.domestic_value == 240
    assert summary.global_value == 112000
    assert summary.cash_value == 71000
    assert summary.usd_krw_rate == 1400
    assert summary.asset_allocation[0]["weight"] > 0
    assert (
        next(row for row in summary.asset_returns if row["ticker"] == "AAPL")["market_value"]
        == 112000
    )
    assert (
        next(row for row in summary.daily_asset_changes if row["ticker"] == "AAPL")[
            "daily_profit_loss"
        ]
        == 7000
    )
    assert len(summary.value_history) == 2
    assert summary.value_history[-1]["total_market_value"] == summary.total_market_value
    assert summary.value_history[-1]["daily_profit_loss"] == summary.daily_profit_loss


def test_portfolio_summary_excludes_zero_quantity_assets():
    repo = InMemoryRepository()
    repo.create_asset(
        {
            "source": "toss_api",
            "external_provider": "toss_invest",
            "external_account_id": "1",
            "external_asset_key": "US:MSFT",
            "market": "US",
            "ticker": "MSFT",
            "name": "Microsoft",
            "quantity": 0,
            "avg_price": 300,
            "currency": "USD",
        }
    )

    summary = PortfolioService(repo, FakeMarketData()).get_summary()

    assert summary.asset_allocation == []
    assert summary.asset_returns == []


def test_portfolio_summary_prefers_saved_snapshots_for_value_history():
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
    repo.create_portfolio_snapshot(
        {
            "report_type": "domestic",
            "snapshot_date": "2026-05-20",
            "total_market_value": 1000,
        }
    )
    repo.create_portfolio_snapshot(
        {
            "report_type": "global",
            "snapshot_date": "2026-05-21",
            "total_market_value": 1200,
        }
    )

    summary = PortfolioService(repo, None).get_summary()

    assert len(summary.value_history) == 2
    assert summary.value_history[-1]["source"] == "snapshot"
    assert summary.value_history[-1]["daily_profit_loss"] == 200


def test_portfolio_summary_refreshes_usd_krw_rate_when_available():
    class FxMarketData(FakeMarketData):
        def fetch_usd_krw_rate(self, fallback=None):
            return 1388.123456

    repo = InMemoryRepository()
    repo.upsert_settings({"usd_krw_rate": 1400})

    summary = PortfolioService(repo, FxMarketData()).get_summary()

    assert summary.usd_krw_rate == 1388.1235
    assert repo.get_settings()["usd_krw_rate"] == 1388.1235


def test_portfolio_snapshot_uses_current_summary_without_ai():
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

    result = PortfolioService(repo, None).create_snapshot()

    assert result["summary"]["total_market_value"] == 1000
    assert result["snapshot"]["report_type"] == "manual"
    assert repo.list_portfolio_snapshots()[0]["total_market_value"] == 1000


def test_benchmark_service_returns_index_actual_and_alphapilot_series():
    class BenchmarkMarketData:
        def fetch_major_indices(self, report_type, lookback_days, stale_data_business_days):
            labels = ["KOSPI", "KOSDAQ"] if report_type == "domestic" else ["S&P 500", "NASDAQ"]
            return {
                label: SimpleNamespace(
                    dataframe=pd.DataFrame(
                        {"close": [100, 105]},
                        index=pd.date_range("2026-05-20", periods=2, freq="B"),
                    )
                )
                for label in labels
            }

        def fetch_price_history(
            self, market, ticker, lookback_days=180, stale_data_business_days=2
        ):
            return SimpleNamespace(
                dataframe=pd.DataFrame(
                    {"close": [10, 12]},
                    index=pd.date_range("2026-05-20", periods=2, freq="B"),
                )
            )

    repo = InMemoryRepository()
    repo.create_portfolio_snapshot(
        {"snapshot_date": "2026-05-20", "report_type": "manual", "total_market_value": 1000}
    )
    repo.create_portfolio_snapshot(
        {"snapshot_date": "2026-05-21", "report_type": "manual", "total_market_value": 1100}
    )
    repo.create_recommendation_cycle(
        {
            "ticker": "AAPL",
            "name": "Apple",
            "action": "BUY",
            "report_type": "global",
            "horizon": "medium",
            "reference_price": 10,
            "started_at": "2026-05-20T00:00:00+00:00",
        }
    )

    result = BenchmarkService(repo, BenchmarkMarketData()).get_return_series(days=7)
    by_key = {row["key"]: row for row in result["series"]}

    assert by_key["kospi"]["points"][-1]["return_rate"] == 5
    assert by_key["actual_portfolio"]["points"][-1]["return_rate"] == 10
    assert by_key["alphapilot"]["points"][-1]["return_rate"] == 20
