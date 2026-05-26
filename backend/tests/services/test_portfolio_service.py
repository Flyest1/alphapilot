from types import SimpleNamespace

from app.db.supabase_client import InMemoryRepository
from app.services.portfolio_service import PortfolioService


class FakeMarketData:
    def fetch_price_history(self, market, ticker):
        prices = {"005930": 120, "AAPL": 80}
        return SimpleNamespace(is_stale=False, current_price=prices[ticker])


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
    assert summary.domestic_value == 240
    assert summary.global_value == 112000
    assert summary.cash_value == 71000
    assert summary.usd_krw_rate == 1400
    assert summary.asset_allocation[0]["weight"] > 0
    assert (
        next(row for row in summary.asset_returns if row["ticker"] == "AAPL")["market_value"]
        == 112000
    )
