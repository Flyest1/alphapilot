from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import EnvironmentSettings, get_environment_settings
from app.db.supabase_client import Repository

TOSS_BASE_URL = "https://openapi.tossinvest.com"
TOSS_PROVIDER = "toss_invest"
TOSS_ASSET_SOURCE = "toss_api"


class TossInvestError(RuntimeError):
    pass


class TossInvestConfigurationError(TossInvestError):
    pass


class TossInvestService:
    def __init__(
        self,
        repository: Repository,
        env: EnvironmentSettings | None = None,
        http_request: Any | None = None,
    ) -> None:
        self.repository = repository
        self.env = env or get_environment_settings()
        self.http_request = http_request or self._http_request

    def status(self) -> dict[str, Any]:
        return {
            "configured": self._credentials_configured(),
            "client_id_configured": bool(self.env.toss_invest_client_id),
            "client_secret_configured": bool(self.env.toss_invest_client_secret),
            "account_id_configured": bool(self.env.toss_invest_account_id),
            "provider": TOSS_PROVIDER,
            "mode": "read_only",
        }

    def sync_holdings(self) -> dict[str, Any]:
        self._ensure_configured()
        token = self._issue_token()
        accounts = self._get_accounts(token)
        account = self._select_account(accounts)
        holdings = self._get_holdings(token, str(account["account_seq"]))
        items = list(holdings.get("items") or [])

        synced_at = datetime.now(timezone.utc).isoformat()
        created_count = 0
        updated_count = 0
        synced_assets = []
        seen_keys = set()
        for item in items:
            asset_data = self._asset_from_holding(item, account, synced_at)
            seen_keys.add(asset_data["external_asset_key"])
            existing = self.repository.get_asset_by_external_key(
                TOSS_PROVIDER,
                asset_data["external_account_id"],
                asset_data["external_asset_key"],
            )
            asset = self.repository.upsert_external_asset(asset_data)
            if existing:
                updated_count += 1
            else:
                created_count += 1
            synced_assets.append(asset)

        stale_count = self._zero_missing_assets(account, seen_keys, synced_at)
        duplicate_manual_assets = self._manual_duplicates(synced_assets)

        return {
            "provider": TOSS_PROVIDER,
            "mode": "read_only",
            "account": account,
            "synced_at": synced_at,
            "synced_count": len(synced_assets),
            "created_count": created_count,
            "updated_count": updated_count,
            "stale_count": stale_count,
            "duplicate_manual_assets": duplicate_manual_assets,
            "overview": {
                "total_purchase_amount": holdings.get("totalPurchaseAmount"),
                "market_value": holdings.get("marketValue"),
                "profit_loss": holdings.get("profitLoss"),
                "daily_profit_loss": holdings.get("dailyProfitLoss"),
            },
        }

    def _credentials_configured(self) -> bool:
        return bool(self.env.toss_invest_client_id and self.env.toss_invest_client_secret)

    def _ensure_configured(self) -> None:
        if not self._credentials_configured():
            raise TossInvestConfigurationError(
                "Toss Invest API credentials are not configured on the backend."
            )

    def _issue_token(self) -> str:
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.env.toss_invest_client_id,
            "client_secret": self.env.toss_invest_client_secret,
        }
        response = self.http_request(
            "POST",
            "/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=urlencode(payload).encode("utf-8"),
        )
        token = response.get("access_token")
        token_type = response.get("token_type")
        if not token or token_type != "Bearer":
            raise TossInvestError("Toss Invest token response is invalid.")
        return str(token)

    def _get_accounts(self, token: str) -> list[dict[str, Any]]:
        response = self.http_request(
            "GET",
            "/api/v1/accounts",
            headers={"Authorization": f"Bearer {token}"},
        )
        result = response.get("result")
        return result if isinstance(result, list) else []

    def _get_holdings(self, token: str, account_seq: str) -> dict[str, Any]:
        response = self.http_request(
            "GET",
            "/api/v1/holdings",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Tossinvest-Account": account_seq,
            },
        )
        result = response.get("result")
        if not isinstance(result, dict):
            raise TossInvestError("Toss Invest holdings response is invalid.")
        return result

    def _select_account(self, accounts: list[dict[str, Any]]) -> dict[str, Any]:
        configured = str(self.env.toss_invest_account_id or "").strip()
        selected = None
        if configured:
            for account in accounts:
                if configured in {
                    str(account.get("accountSeq") or ""),
                    str(account.get("accountNo") or ""),
                }:
                    selected = account
                    break
            if selected is None and configured.isdigit():
                return {
                    "account_seq": configured,
                    "account_no": None,
                    "account_type": None,
                    "source": "env",
                }
        if selected is None:
            selected = next(
                (account for account in accounts if account.get("accountType") == "BROKERAGE"),
                accounts[0] if accounts else None,
            )
        if selected is None:
            raise TossInvestConfigurationError("No Toss Invest account is available.")
        account_seq = selected.get("accountSeq")
        if account_seq is None:
            raise TossInvestError("Toss Invest account response is missing accountSeq.")
        return {
            "account_seq": str(account_seq),
            "account_no": selected.get("accountNo"),
            "account_type": selected.get("accountType"),
            "source": "accounts_api",
        }

    def _asset_from_holding(
        self,
        item: dict[str, Any],
        account: dict[str, Any],
        synced_at: str,
    ) -> dict[str, Any]:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            raise TossInvestError("Toss Invest holding item is missing symbol.")
        market_country = str(item.get("marketCountry") or "").upper()
        market = "KR" if market_country == "KR" else "US"
        currency = str(item.get("currency") or ("KRW" if market == "KR" else "USD")).upper()
        account_id = str(account["account_seq"])
        external_key = f"{market}:{symbol}"
        return {
            "source": TOSS_ASSET_SOURCE,
            "external_provider": TOSS_PROVIDER,
            "external_account_id": account_id,
            "external_asset_key": external_key,
            "market": market,
            "ticker": symbol,
            "name": str(item.get("name") or symbol),
            "quantity": _to_float(item.get("quantity")),
            "avg_price": _to_float(item.get("averagePurchasePrice")),
            "currency": currency,
            "memo": "Toss Invest Open API read-only sync",
            "synced_at": synced_at,
            "external_payload": item,
        }

    def _zero_missing_assets(
        self,
        account: dict[str, Any],
        seen_keys: set[str],
        synced_at: str,
    ) -> int:
        account_id = str(account["account_seq"])
        stale_count = 0
        for asset in self.repository.list_assets():
            if (
                asset.get("source") != TOSS_ASSET_SOURCE
                or asset.get("external_provider") != TOSS_PROVIDER
                or asset.get("external_account_id") != account_id
                or asset.get("external_asset_key") in seen_keys
            ):
                continue
            payload = dict(asset.get("external_payload") or {})
            payload["missing_from_latest_sync"] = True
            self.repository.update_asset(
                asset["id"],
                {
                    "quantity": 0,
                    "synced_at": synced_at,
                    "external_payload": payload,
                },
            )
            stale_count += 1
        return stale_count

    def _manual_duplicates(self, synced_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        synced_keys = {
            (str(asset.get("market")), str(asset.get("ticker")).upper()) for asset in synced_assets
        }
        duplicates = []
        for asset in self.repository.list_assets():
            if str(asset.get("source") or "manual") != "manual":
                continue
            key = (str(asset.get("market")), str(asset.get("ticker")).upper())
            if key not in synced_keys:
                continue
            duplicates.append(
                {
                    "id": asset.get("id"),
                    "market": asset.get("market"),
                    "ticker": asset.get("ticker"),
                    "name": asset.get("name"),
                    "quantity": asset.get("quantity"),
                    "avg_price": asset.get("avg_price"),
                }
            )
        return duplicates

    def _http_request(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> dict[str, Any]:
        request = Request(
            f"{TOSS_BASE_URL}{path}",
            data=body,
            headers=headers or {},
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = _safe_error_detail(exc)
            raise TossInvestError(f"Toss Invest API request failed: {exc.code} {detail}") from exc
        except URLError as exc:
            raise TossInvestError("Toss Invest API connection failed.") from exc
        return json.loads(raw or "{}")


def _to_float(value: Any) -> float:
    try:
        return float(Decimal(str(value or "0")))
    except (InvalidOperation, ValueError):
        return 0.0


def _safe_error_detail(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8")
    except Exception:
        return ""
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body[:200]
    if isinstance(parsed, dict):
        return str(parsed.get("error") or parsed.get("message") or parsed.get("detail") or "")
    return ""
