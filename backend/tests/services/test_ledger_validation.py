from decimal import Decimal

import pytest

from app.services.ledger.validation import validate_events


def event(**changes):
    return {
        "account_id": "demo",
        "event_key": "trade-1",
        "revision": 1,
        "source_type": "statement",
        "source_key": "document-1:row-1",
        "source_record_hash": "a" * 64,
        "event_type": "trade",
        "event_date": "2026-09-01",
        "effective_at": "2026-09-01T10:00:00+09:00",
        "observed_at": "2026-09-02T10:00:00+09:00",
        "timezone": "Asia/Seoul",
        "precision": "exact_time",
        "quality": "verified",
        "currency": "USD",
        "market": "US",
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": "2",
        "gross_amount": "200",
        "fee": "1",
        "tax": "0",
        "net_cash_amount": "-201",
        "settlement_date": "2026-09-03",
        **changes,
    }


def test_preserves_decimal_precision_and_missing_cost():
    result = validate_events([event(gross_amount="200.000000000001", fee=None)])
    assert not result["errors"]
    assert result["events"][0].gross_amount == Decimal("200.000000000001")
    assert result["events"][0].fee is None


@pytest.mark.parametrize(
    "change",
    [
        {"gross_amount": 200.1},
        {"quantity": True},
        {"fee": "NaN"},
        {"gross_amount": "1.0000000000001"},
        {"gross_amount": "9" * 27},
        {"source_record_hash": "invalid"},
        {"currency": "EUR"},
        {"effective_at": "2026-09-01T10:00:00"},
        {"observed_at": "2026-08-31T00:00:00Z"},
        {"settlement_confirmed": True},
        {"timezone": "fake/zone"},
        {"settlement_date": "2026-08-31"},
        {"unexpected": "field"},
    ],
)
def test_invalid_row_does_not_discard_valid_rows(change):
    result = validate_events([event(**change), event(event_key="valid")])
    assert len(result["errors"]) == 1
    assert len(result["events"]) == 1
    assert result["errors"][0]["row"] == 0


def test_date_only_evidence_is_not_given_a_fabricated_time():
    result = validate_events([event(precision="date_only", effective_at=None)])
    assert result["events"][0].effective_at is None


def test_full_numeric_precision_is_accepted_without_context_rounding():
    number = "99999999999999999999999999.999999999999"
    result = validate_events([event(gross_amount=number)])
    assert not result["errors"]
    assert str(result["events"][0].gross_amount) == number
