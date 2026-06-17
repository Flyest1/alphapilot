from app.config import EnvironmentSettings
from app.db.supabase_client import InMemoryRepository
from app.services.toss_invest_service import TossInvestService


def _env(account_id: str | None = "1") -> EnvironmentSettings:
    return EnvironmentSettings(
        app_env="test",
        supabase_url=None,
        supabase_service_role_key=None,
        supabase_anon_key=None,
        openai_api_key=None,
        scheduler_secret="scheduler",
        api_access_token="api",
        frontend_origin="http://localhost:5173",
        market_data_provider_kr=None,
        market_data_provider_us=None,
        telegram_bot_token=None,
        telegram_chat_id=None,
        toss_invest_client_id="client-id",
        toss_invest_client_secret="client-secret",
        toss_invest_account_id=account_id,
    )


def test_toss_sync_upserts_api_assets_and_reports_manual_duplicates():
    repository = InMemoryRepository()
    manual = repository.create_asset(
        {
            "market": "US",
            "ticker": "AAPL",
            "name": "Apple manual",
            "quantity": 2,
            "avg_price": 150,
            "currency": "USD",
        }
    )
    old_linked = repository.create_asset(
        {
            "source": "toss_api",
            "external_provider": "toss_invest",
            "external_account_id": "1",
            "external_asset_key": "US:MSFT",
            "market": "US",
            "ticker": "MSFT",
            "name": "Microsoft",
            "quantity": 1,
            "avg_price": 300,
            "currency": "USD",
        }
    )

    def fake_http(method, path, headers=None, body=None):
        assert path in {"/oauth2/token", "/api/v1/accounts", "/api/v1/holdings"}
        if path == "/oauth2/token":
            assert method == "POST"
            assert b"client_secret=client-secret" in body
            return {"access_token": "token", "token_type": "Bearer", "expires_in": 86400}
        if path == "/api/v1/accounts":
            assert headers["Authorization"] == "Bearer token"
            return {
                "result": [
                    {"accountNo": "12345678901", "accountSeq": 1, "accountType": "BROKERAGE"}
                ]
            }
        assert headers["Authorization"] == "Bearer token"
        assert headers["X-Tossinvest-Account"] == "1"
        return {
            "result": {
                "totalPurchaseAmount": {"krw": "0", "usd": "1553"},
                "marketValue": {},
                "profitLoss": {},
                "dailyProfitLoss": {},
                "items": [
                    {
                        "symbol": "AAPL",
                        "name": "Apple Inc.",
                        "marketCountry": "US",
                        "currency": "USD",
                        "quantity": "10",
                        "lastPrice": "178.5",
                        "averagePurchasePrice": "155.3",
                        "marketValue": {"purchaseAmount": "1553", "amount": "1785"},
                        "profitLoss": {"amount": "232", "rate": "0.1494"},
                        "dailyProfitLoss": {"amount": "25", "rate": "0.0142"},
                        "cost": {"commission": "3.57", "tax": "10"},
                    }
                ],
            }
        }

    result = TossInvestService(repository, env=_env(), http_request=fake_http).sync_holdings()

    assert result["synced_count"] == 1
    assert result["created_count"] == 1
    assert result["stale_count"] == 1
    assert result["duplicate_manual_assets"][0]["id"] == manual["id"]

    linked = repository.get_asset_by_external_key("toss_invest", "1", "US:AAPL")
    assert linked is not None
    assert linked["source"] == "toss_api"
    assert linked["quantity"] == 10
    assert linked["avg_price"] == 155.3

    stale = repository.get_asset(old_linked["id"])
    assert stale["quantity"] == 0
    assert stale["external_payload"]["missing_from_latest_sync"] is True


def test_toss_status_does_not_expose_credentials():
    repository = InMemoryRepository()

    status = TossInvestService(repository, env=_env()).status()

    assert status == {
        "configured": True,
        "client_id_configured": True,
        "client_secret_configured": True,
        "account_id_configured": True,
        "provider": "toss_invest",
        "mode": "read_only",
    }
