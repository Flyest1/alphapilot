"""Read-only Toss order evidence collection without ledger publication."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from time import sleep as default_sleep
from typing import Any, Callable, Iterable
from urllib.parse import urlencode

from app.services.toss_invest_service import (
    TossInvestError,
    TossInvestRateLimitError,
    TossInvestService,
)

KNOWN_ORDER_STATUSES = {
    "PENDING",
    "PENDING_CANCEL",
    "PENDING_REPLACE",
    "PARTIAL_FILLED",
    "FILLED",
    "CANCELED",
    "REJECTED",
    "CANCEL_REJECTED",
    "REPLACE_REJECTED",
    "REPLACED",
}
ORDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9.\-]+$")
DECIMAL_PATTERN = re.compile(r"^\d+(\.\d+)?$")


class TossOrderEvidenceError(TossInvestError):
    pass


class TossOrderEvidenceReader:
    def __init__(
        self,
        service: TossInvestService,
        *,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = default_sleep,
        contract_version: str = "1.2.19",
        max_read_attempts: int = 3,
        max_retry_delay_seconds: float = 5,
    ) -> None:
        self.service = service
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep
        self.contract_version = contract_version
        self.max_read_attempts = max_read_attempts
        self.max_retry_delay_seconds = max_retry_delay_seconds

    def collect(
        self,
        *,
        account_id: str,
        ordered_from: date,
        ordered_to: date,
        known_open_order_ids: Iterable[str] = (),
    ) -> dict[str, Any]:
        if not account_id.strip():
            raise TossOrderEvidenceError("Toss order evidence requires an explicit account.")
        if ordered_from > ordered_to:
            raise TossOrderEvidenceError("Toss order evidence date range is invalid.")
        known_ids = tuple(dict.fromkeys(str(value) for value in known_open_order_ids))
        for order_id in known_ids:
            self._validate_order_id(order_id)

        queried_from = ordered_from - timedelta(days=1)
        raw_pages: list[dict[str, Any]] = []
        listed_orders: dict[str, dict[str, Any]] = {}
        with self.service.read_session(account_id) as session:
            open_result = self._get_page(
                session,
                status="OPEN",
                ordered_from=queried_from,
                ordered_to=ordered_to,
            )
            raw_pages.append({"status": "OPEN", "cursor": None, "result": deepcopy(open_result)})
            self._add_listed_orders(listed_orders, open_result["orders"])

            cursor = None
            seen_cursors: set[str] = set()
            closed_page_count = 0
            while True:
                closed_page_count += 1
                if closed_page_count > 100:
                    raise TossOrderEvidenceError("Toss order pagination did not progress.")
                closed_result = self._get_page(
                    session,
                    status="CLOSED",
                    ordered_from=queried_from,
                    ordered_to=ordered_to,
                    cursor=cursor,
                )
                raw_pages.append(
                    {"status": "CLOSED", "cursor": cursor, "result": deepcopy(closed_result)}
                )
                self._add_listed_orders(listed_orders, closed_result["orders"])
                if not closed_result["hasNext"]:
                    break
                next_cursor = closed_result["nextCursor"]
                if not closed_result["orders"] or next_cursor in seen_cursors:
                    raise TossOrderEvidenceError("Toss order pagination did not progress.")
                seen_cursors.add(next_cursor)
                cursor = next_cursor

            observations = []
            for order_id in sorted(set(listed_orders) | set(known_ids)):
                response = self._read(session, f"/api/v1/orders/{order_id}")
                detail = response.get("result") if isinstance(response, dict) else None
                observations.append(self._observation(account_id, detail, expected_id=order_id))

        oldest_ordered_at = min(
            (item["payload"]["orderedAt"] for item in observations),
            default=None,
        )
        return {
            "provider": "toss_invest",
            "mode": "read_only_evidence",
            "contract_version": self.contract_version,
            "account_id": account_id,
            "observed_at": self.now().isoformat(),
            "raw_pages": raw_pages,
            "observations": observations,
            "coverage": {
                "api_pages_complete": True,
                "economic_coverage_verified": False,
                "unsupported_order_types_possible": True,
                "requested_from": ordered_from.isoformat(),
                "requested_to": ordered_to.isoformat(),
                "queried_from": queried_from.isoformat(),
                "queried_to": ordered_to.isoformat(),
                "oldest_ordered_at": oldest_ordered_at,
                "warnings": [
                    "API page completion does not prove complete account trade coverage.",
                    "Unsupported order types and non-order cash flows may be absent.",
                ],
            },
        }

    def _get_page(
        self,
        session,
        *,
        status: str,
        ordered_from: date,
        ordered_to: date,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {
            "status": status,
            "from": ordered_from.isoformat(),
            "to": ordered_to.isoformat(),
        }
        if status == "CLOSED":
            query["limit"] = 100
            if cursor is not None:
                query["cursor"] = cursor
        response = self._read(session, f"/api/v1/orders?{urlencode(query)}")
        result = response.get("result") if isinstance(response, dict) else None
        if not isinstance(result, dict):
            raise TossOrderEvidenceError("Toss order list response is invalid.")
        orders = result.get("orders")
        next_cursor = result.get("nextCursor")
        has_next = result.get("hasNext")
        if not isinstance(orders, list) or not all(isinstance(item, dict) for item in orders):
            raise TossOrderEvidenceError("Toss order list must contain order objects.")
        if type(has_next) is not bool:
            raise TossOrderEvidenceError("Toss order list pagination state is invalid.")
        if has_next and (not isinstance(next_cursor, str) or not next_cursor):
            raise TossOrderEvidenceError("Toss order list next cursor is missing.")
        if not has_next and next_cursor is not None:
            raise TossOrderEvidenceError("Toss order list has an unexpected next cursor.")
        if status == "OPEN" and (has_next or next_cursor is not None):
            raise TossOrderEvidenceError("Toss OPEN order list must not contain pagination state.")
        return {"orders": orders, "nextCursor": next_cursor, "hasNext": has_next}

    def _read(self, session, path: str) -> dict[str, Any]:
        for attempt in range(self.max_read_attempts):
            try:
                return session.get(path)
            except TossInvestRateLimitError as exc:
                if (
                    attempt + 1 >= self.max_read_attempts
                    or exc.retry_after_seconds > self.max_retry_delay_seconds
                ):
                    raise
                self.sleep(exc.retry_after_seconds)
        raise AssertionError("unreachable")

    def _add_listed_orders(
        self, destination: dict[str, dict[str, Any]], orders: list[dict[str, Any]]
    ) -> None:
        for order in orders:
            order_id = order.get("orderId")
            self._validate_order_id(order_id)
            destination[str(order_id)] = order

    def _observation(
        self,
        account_id: str,
        payload: Any,
        *,
        expected_id: str,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("orderId") != expected_id:
            raise TossOrderEvidenceError("Toss order detail does not match the requested order.")
        required = {
            "symbol",
            "side",
            "orderType",
            "timeInForce",
            "status",
            "quantity",
            "currency",
            "orderedAt",
            "execution",
        }
        if not required.issubset(payload) or not isinstance(payload["execution"], dict):
            raise TossOrderEvidenceError("Toss order detail is incomplete.")
        self._validate_detail(payload)
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        status = str(payload["status"])
        return {
            "account_id": account_id,
            "order_id": expected_id,
            "source_type": "api",
            "source_key": f"toss_order:{expected_id}",
            "payload_hash": sha256(canonical.encode("utf-8")).hexdigest(),
            "event_type": "execution_aggregate",
            "precision": "aggregate",
            "quality": "provisional" if status in KNOWN_ORDER_STATUSES else "quarantined",
            "payload": deepcopy(payload),
        }

    def _validate_detail(self, payload: dict[str, Any]) -> None:
        execution = payload["execution"]
        execution_required = {
            "filledQuantity",
            "averageFilledPrice",
            "filledAmount",
            "commission",
            "tax",
            "filledAt",
            "settlementDate",
        }
        if not execution_required.issubset(execution):
            raise TossOrderEvidenceError("Toss order detail is invalid.")
        if (
            not isinstance(payload["symbol"], str)
            or not SYMBOL_PATTERN.fullmatch(payload["symbol"])
            or payload["side"] not in {"BUY", "SELL"}
            or payload["currency"] not in {"KRW", "USD"}
            or not isinstance(payload["orderType"], str)
            or not payload["orderType"]
            or not isinstance(payload["timeInForce"], str)
            or not payload["timeInForce"]
            or not isinstance(payload["status"], str)
            or not payload["status"]
        ):
            raise TossOrderEvidenceError("Toss order detail is invalid.")

        quantity = self._decimal(payload["quantity"], nullable=False)
        filled_quantity = self._decimal(execution["filledQuantity"], nullable=False)
        if quantity <= 0 or filled_quantity < 0 or filled_quantity > quantity:
            raise TossOrderEvidenceError("Toss order detail is invalid.")
        for value in (payload.get("price"), payload.get("orderAmount")):
            self._decimal(value, nullable=True)
        for key in ("averageFilledPrice", "filledAmount", "commission", "tax"):
            self._decimal(execution[key], nullable=True)
        self._aware_datetime(payload["orderedAt"])
        if payload.get("canceledAt") is not None:
            self._aware_datetime(payload["canceledAt"])
        if execution["filledAt"] is not None:
            self._aware_datetime(execution["filledAt"])
        if execution["settlementDate"] is not None:
            try:
                date.fromisoformat(execution["settlementDate"])
            except (TypeError, ValueError):
                raise TossOrderEvidenceError("Toss order detail is invalid.") from None

    @staticmethod
    def _decimal(value: Any, *, nullable: bool) -> Decimal | None:
        if value is None and nullable:
            return None
        if not isinstance(value, str) or len(value) > 30 or not DECIMAL_PATTERN.fullmatch(value):
            raise TossOrderEvidenceError("Toss order detail is invalid.")
        try:
            parsed = Decimal(value)
        except InvalidOperation:
            raise TossOrderEvidenceError("Toss order detail is invalid.") from None
        if not parsed.is_finite():
            raise TossOrderEvidenceError("Toss order detail is invalid.")
        return parsed

    @staticmethod
    def _aware_datetime(value: Any) -> datetime:
        if not isinstance(value, str):
            raise TossOrderEvidenceError("Toss order detail is invalid.")
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise TossOrderEvidenceError("Toss order detail is invalid.") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise TossOrderEvidenceError("Toss order detail is invalid.")
        return parsed

    @staticmethod
    def _validate_order_id(order_id: Any) -> None:
        if not isinstance(order_id, str) or not ORDER_ID_PATTERN.fullmatch(order_id):
            raise TossOrderEvidenceError("Toss order identifier is invalid.")
