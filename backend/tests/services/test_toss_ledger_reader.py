from datetime import date, datetime, timezone
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
import importlib
import importlib.util
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from app.config import EnvironmentSettings
from app.db.supabase_client import InMemoryRepository
from app.services.toss_invest_service import TossInvestConfigurationError, TossInvestService


def _env() -> EnvironmentSettings:
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
        toss_invest_account_id="1",
    )


def _order(order_id: str, *, status: str, filled: str = "0") -> dict:
    return {
        "orderId": order_id,
        "symbol": "AAPL",
        "side": "BUY",
        "orderType": "LIMIT",
        "timeInForce": "DAY",
        "status": status,
        "price": "180.00",
        "quantity": "5",
        "orderAmount": None,
        "currency": "USD",
        "orderedAt": "2026-09-20T22:30:00+09:00",
        "canceledAt": None,
        "execution": {
            "filledQuantity": filled,
            "averageFilledPrice": "179.50" if filled != "0" else None,
            "filledAmount": "359.00" if filled != "0" else None,
            "commission": "0.50" if filled != "0" else None,
            "tax": "0" if filled != "0" else None,
            "filledAt": "2026-09-20T22:31:00+09:00" if filled != "0" else None,
            "settlementDate": None,
        },
    }


def test_collects_read_only_order_evidence_without_secrets_or_completeness_claims():
    spec = importlib.util.find_spec("app.services.ledger.toss_reader")
    assert spec is not None, "the read-only Toss order evidence reader is not implemented"
    module = importlib.import_module("app.services.ledger.toss_reader")
    calls: list[tuple[str, str, dict | None, bytes | None]] = []
    open_order = _order("open-1", status="PARTIAL_FILLED", filled="2")
    closed_1 = _order("closed-1", status="FILLED", filled="5")
    closed_2 = _order("closed-2", status="CANCELED", filled="1")
    known_open = _order("known-open", status="PENDING")
    details = {item["orderId"]: item for item in (open_order, closed_1, closed_2, known_open)}

    def fake_http(method, path, headers=None, body=None):
        calls.append((method, path, headers, body))
        if path == "/oauth2/token":
            return {"access_token": "secret-token", "token_type": "Bearer", "expires_in": 86400}
        if path == "/api/v1/accounts":
            return {
                "result": [
                    {"accountNo": "secret-account-no", "accountSeq": 1, "accountType": "BROKERAGE"}
                ]
            }
        split = urlsplit(path)
        if split.path.startswith("/api/v1/orders/"):
            order_id = split.path.rsplit("/", 1)[1]
            return {"result": details[order_id]}
        query = parse_qs(split.query)
        assert split.path == "/api/v1/orders"
        assert query["from"] == ["2026-09-19"]
        assert query["to"] == ["2026-09-21"]
        if query["status"] == ["OPEN"]:
            return {"result": {"orders": [open_order], "nextCursor": None, "hasNext": False}}
        if "cursor" not in query:
            return {"result": {"orders": [closed_1], "nextCursor": "cursor-2", "hasNext": True}}
        assert query["cursor"] == ["cursor-2"]
        return {"result": {"orders": [closed_2], "nextCursor": None, "hasNext": False}}

    service = TossInvestService(InMemoryRepository(), env=_env(), http_request=fake_http)
    reader = module.TossOrderEvidenceReader(
        service,
        now=lambda: datetime(2026, 9, 29, tzinfo=timezone.utc),
        sleep=lambda _seconds: None,
    )

    packet = reader.collect(
        account_id="1",
        ordered_from=date(2026, 9, 20),
        ordered_to=date(2026, 9, 21),
        known_open_order_ids=("known-open",),
    )

    assert [page["status"] for page in packet["raw_pages"]] == ["OPEN", "CLOSED", "CLOSED"]
    assert [item["order_id"] for item in packet["observations"]] == [
        "closed-1",
        "closed-2",
        "known-open",
        "open-1",
    ]
    assert all(item["event_type"] == "execution_aggregate" for item in packet["observations"])
    assert all(item["precision"] == "aggregate" for item in packet["observations"])
    assert packet["coverage"] == {
        "api_pages_complete": True,
        "economic_coverage_verified": False,
        "unsupported_order_types_possible": True,
        "requested_from": "2026-09-20",
        "requested_to": "2026-09-21",
        "queried_from": "2026-09-19",
        "queried_to": "2026-09-21",
        "oldest_ordered_at": "2026-09-20T22:30:00+09:00",
        "warnings": [
            "API page completion does not prove complete account trade coverage.",
            "Unsupported order types and non-order cash flows may be absent.",
        ],
    }
    serialized = json.dumps(packet, ensure_ascii=False)
    assert "secret-token" not in serialized
    assert "secret-account-no" not in serialized
    assert "Authorization" not in serialized
    assert "X-Tossinvest-Account" not in serialized
    assert {method for method, path, _headers, _body in calls if path != "/oauth2/token"} == {"GET"}
    assert not any(path.endswith("/cancel") or path.endswith("/modify") for _, path, _, _ in calls)


@pytest.mark.parametrize("failure", ["repeated_cursor", "empty_intermediate_page"])
def test_closed_pagination_fails_closed_on_non_progress(failure):
    module = importlib.import_module("app.services.ledger.toss_reader")
    closed_calls = 0

    def fake_http(method, path, headers=None, body=None):
        nonlocal closed_calls
        if path == "/oauth2/token":
            return {"access_token": "token", "token_type": "Bearer"}
        if path == "/api/v1/accounts":
            return {"result": [{"accountSeq": 1, "accountType": "BROKERAGE"}]}
        query = parse_qs(urlsplit(path).query)
        if query["status"] == ["OPEN"]:
            return {"result": {"orders": [], "nextCursor": None, "hasNext": False}}
        closed_calls += 1
        if closed_calls > 2:
            raise AssertionError("collector followed a non-progressing cursor")
        orders = (
            [] if failure == "empty_intermediate_page" else [_order("closed-1", status="FILLED")]
        )
        return {
            "result": {
                "orders": orders,
                "nextCursor": "same-cursor",
                "hasNext": True,
            }
        }

    reader = module.TossOrderEvidenceReader(
        TossInvestService(InMemoryRepository(), env=_env(), http_request=fake_http),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(module.TossOrderEvidenceError, match="pagination did not progress"):
        reader.collect(
            account_id="1",
            ordered_from=date(2026, 9, 20),
            ordered_to=date(2026, 9, 21),
        )


def test_open_response_rejects_pagination_state():
    module = importlib.import_module("app.services.ledger.toss_reader")

    def fake_http(method, path, headers=None, body=None):
        if path == "/oauth2/token":
            return {"access_token": "token", "token_type": "Bearer"}
        if path == "/api/v1/accounts":
            return {"result": [{"accountSeq": 1, "accountType": "BROKERAGE"}]}
        return {
            "result": {
                "orders": [_order("open-1", status="PENDING")],
                "nextCursor": "unexpected-cursor",
                "hasNext": True,
            }
        }

    reader = module.TossOrderEvidenceReader(
        TossInvestService(InMemoryRepository(), env=_env(), http_request=fake_http),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(module.TossOrderEvidenceError, match="OPEN.*pagination"):
        reader.collect(
            account_id="1",
            ordered_from=date(2026, 9, 20),
            ordered_to=date(2026, 9, 21),
        )


@pytest.mark.parametrize("eventual_success", [True, False])
def test_rate_limit_retry_is_bounded_for_read_requests(eventual_success):
    module = importlib.import_module("app.services.ledger.toss_reader")
    toss_module = importlib.import_module("app.services.toss_invest_service")
    attempts = 0
    delays: list[float] = []

    def fake_http(method, path, headers=None, body=None):
        nonlocal attempts
        if path == "/oauth2/token":
            return {"access_token": "token", "token_type": "Bearer"}
        if path == "/api/v1/accounts":
            return {"result": [{"accountSeq": 1, "accountType": "BROKERAGE"}]}
        attempts += 1
        if attempts <= 2 or not eventual_success:
            raise toss_module.TossInvestRateLimitError(retry_after_seconds=0.25)
        return {"result": {"orders": [], "nextCursor": None, "hasNext": False}}

    reader = module.TossOrderEvidenceReader(
        TossInvestService(InMemoryRepository(), env=_env(), http_request=fake_http),
        sleep=delays.append,
    )
    request = {
        "account_id": "1",
        "ordered_from": date(2026, 9, 20),
        "ordered_to": date(2026, 9, 21),
    }

    if eventual_success:
        assert reader.collect(**request)["coverage"]["api_pages_complete"] is True
    else:
        with pytest.raises(toss_module.TossInvestRateLimitError):
            reader.collect(**request)

    assert attempts == (4 if eventual_success else 3)
    assert delays == [0.25, 0.25]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("quantity",), True),
        (("execution", "filledQuantity"), "-1"),
        (("execution", "commission"), "NaN"),
        (("orderedAt",), "2026-09-20T22:30:00"),
    ],
)
def test_malformed_order_detail_is_rejected(path, value):
    module = importlib.import_module("app.services.ledger.toss_reader")
    malformed = _order("order-1", status="FILLED", filled="5")
    target = malformed
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    def fake_http(method, request_path, headers=None, body=None):
        if request_path == "/oauth2/token":
            return {"access_token": "token", "token_type": "Bearer"}
        if request_path == "/api/v1/accounts":
            return {"result": [{"accountSeq": 1, "accountType": "BROKERAGE"}]}
        if urlsplit(request_path).path == "/api/v1/orders":
            query = parse_qs(urlsplit(request_path).query)
            orders = [deepcopy(malformed)] if query["status"] == ["OPEN"] else []
            return {"result": {"orders": orders, "nextCursor": None, "hasNext": False}}
        return {"result": deepcopy(malformed)}

    reader = module.TossOrderEvidenceReader(
        TossInvestService(InMemoryRepository(), env=_env(), http_request=fake_http),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(module.TossOrderEvidenceError, match="detail is invalid"):
        reader.collect(
            account_id="1",
            ordered_from=date(2026, 9, 20),
            ordered_to=date(2026, 9, 21),
        )


def test_unknown_order_status_is_preserved_but_quarantined():
    module = importlib.import_module("app.services.ledger.toss_reader")
    unknown = _order("order-1", status="BROKER_NEW_STATUS", filled="1")

    def fake_http(method, request_path, headers=None, body=None):
        if request_path == "/oauth2/token":
            return {"access_token": "token", "token_type": "Bearer"}
        if request_path == "/api/v1/accounts":
            return {"result": [{"accountSeq": 1, "accountType": "BROKERAGE"}]}
        if urlsplit(request_path).path == "/api/v1/orders":
            query = parse_qs(urlsplit(request_path).query)
            orders = [deepcopy(unknown)] if query["status"] == ["OPEN"] else []
            return {"result": {"orders": orders, "nextCursor": None, "hasNext": False}}
        return {"result": deepcopy(unknown)}

    packet = module.TossOrderEvidenceReader(
        TossInvestService(InMemoryRepository(), env=_env(), http_request=fake_http),
        sleep=lambda _seconds: None,
    ).collect(
        account_id="1",
        ordered_from=date(2026, 9, 20),
        ordered_to=date(2026, 9, 21),
    )

    assert packet["observations"][0]["quality"] == "quarantined"
    assert packet["observations"][0]["payload"]["status"] == "BROKER_NEW_STATUS"


def test_order_collection_and_holdings_sync_serialize_token_scoped_reads():
    module = importlib.import_module("app.services.ledger.toss_reader")
    first_token_started = Event()
    release_first_token = Event()
    second_token_started = Event()
    token_lock = Lock()
    token_count = 0

    def fake_http(method, request_path, headers=None, body=None):
        nonlocal token_count
        if request_path == "/oauth2/token":
            with token_lock:
                token_count += 1
                current = token_count
            if current == 1:
                first_token_started.set()
                assert release_first_token.wait(2)
            else:
                second_token_started.set()
            return {"access_token": f"token-{current}", "token_type": "Bearer"}
        if request_path == "/api/v1/accounts":
            return {"result": [{"accountSeq": 1, "accountType": "BROKERAGE"}]}
        split = urlsplit(request_path)
        if split.path == "/api/v1/orders":
            return {"result": {"orders": [], "nextCursor": None, "hasNext": False}}
        if request_path == "/api/v1/holdings":
            return {"result": {"items": []}}
        if split.path == "/api/v1/buying-power":
            currency = parse_qs(split.query)["currency"][0]
            return {"result": {"currency": currency, "cashBuyingPower": "0"}}
        raise AssertionError(request_path)

    reader = module.TossOrderEvidenceReader(
        TossInvestService(InMemoryRepository(), env=_env(), http_request=fake_http),
        sleep=lambda _seconds: None,
    )
    holdings = TossInvestService(InMemoryRepository(), env=_env(), http_request=fake_http)

    with ThreadPoolExecutor(max_workers=2) as pool:
        read_future = pool.submit(
            reader.collect,
            account_id="1",
            ordered_from=date(2026, 9, 20),
            ordered_to=date(2026, 9, 21),
        )
        assert first_token_started.wait(1)
        sync_future = pool.submit(holdings.sync_holdings)
        assert not second_token_started.wait(0.1)
        release_first_token.set()
        assert read_future.result()["coverage"]["api_pages_complete"] is True
        assert sync_future.result()["mode"] == "read_only"

    assert second_token_started.is_set()


def test_explicit_account_mismatch_stops_before_order_reads():
    module = importlib.import_module("app.services.ledger.toss_reader")
    order_reads = 0

    def fake_http(method, request_path, headers=None, body=None):
        nonlocal order_reads
        if request_path == "/oauth2/token":
            return {"access_token": "token", "token_type": "Bearer"}
        if request_path == "/api/v1/accounts":
            return {"result": [{"accountSeq": 1, "accountType": "BROKERAGE"}]}
        order_reads += 1
        raise AssertionError(request_path)

    reader = module.TossOrderEvidenceReader(
        TossInvestService(InMemoryRepository(), env=_env(), http_request=fake_http),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(TossInvestConfigurationError, match="requested account does not match"):
        reader.collect(
            account_id="2",
            ordered_from=date(2026, 9, 20),
            ordered_to=date(2026, 9, 21),
        )
    assert order_reads == 0
