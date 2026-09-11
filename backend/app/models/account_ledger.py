"""Local evidence contracts; no broker or persistence side effects."""

from datetime import date, datetime
from decimal import Decimal
import re
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def decimal_amount(value):
    if not isinstance(value, (str, Decimal)) or not re.fullmatch(r"-?\d+(\.\d+)?", str(value)):
        raise ValueError("Use a finite decimal string, never float")
    parsed = Decimal(value)
    if abs(parsed) >= Decimal("1e26") or parsed.as_tuple().exponent < -12:
        raise ValueError("Exceeds numeric(38,12) precision")
    return parsed


Amount = Annotated[Decimal, BeforeValidator(decimal_amount)]
Currency = Literal["KRW", "USD"]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^\S(?:.*\S)?$")]


class LedgerEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    account_id: Identifier
    event_key: Identifier
    revision: int = Field(default=1, ge=1, strict=True)
    supersedes_hash: Digest | None = None
    source_type: Literal["api", "statement", "manual"]
    source_key: Identifier
    source_record_hash: Digest
    event_type: Literal[
        "trade",
        "execution_aggregate",
        "deposit",
        "withdrawal",
        "dividend",
        "interest",
        "fx_conversion",
        "security_transfer",
        "corporate_action",
        "reversal",
    ]
    event_date: date
    effective_at: datetime | None = None
    observed_at: datetime
    timezone: str
    precision: Literal["exact_time", "date_only", "aggregate"]
    quality: Literal["verified", "provisional", "quarantined"]
    currency: Currency
    market: Literal["KR", "US"] | None = None
    symbol: Annotated[str, Field(pattern=r"^[A-Z0-9.\-]+$")] | None = None
    side: Literal["BUY", "SELL", "IN", "OUT"] | None = None
    quantity: Amount | None = None
    gross_amount: Amount | None = None
    fee: Amount | None = None
    tax: Amount | None = None
    net_cash_amount: Amount | None = None
    settlement_date: date | None = None
    counter_currency: Currency | None = None
    counter_amount: Amount | None = None

    @model_validator(mode="after")
    def validate_contract(self):
        try:
            zone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown timezone") from None
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at needs timezone")
        if self.precision == "exact_time" and self.effective_at is None:
            raise ValueError("exact_time requires effective_at")
        if self.effective_at is not None:
            if self.effective_at.tzinfo is None:
                raise ValueError("effective_at needs timezone")
            if self.effective_at.astimezone(zone).date() != self.event_date:
                raise ValueError("effective_at must match event_date in declared timezone")
        if self.settlement_date and self.settlement_date < self.event_date:
            raise ValueError("Settlement before event date")
        if self.revision == 1 and self.supersedes_hash is not None:
            raise ValueError("First revision cannot supersede")
        if self.revision > 1 and self.supersedes_hash is None:
            raise ValueError("Correction requires previous evidence hash")
        for key in ("gross_amount", "fee", "tax", "counter_amount"):
            if getattr(self, key) is not None and getattr(self, key) < 0:
                raise ValueError(f"{key} must be nonnegative")
        if self.event_type in {
            "trade",
            "execution_aggregate",
            "security_transfer",
            "corporate_action",
        }:
            if not self.symbol or not self.market or self.quantity is None:
                raise ValueError("Security evidence requires market, symbol and quantity")
            if self.market == "KR" and self.currency != "KRW":
                raise ValueError("KR security requires KRW")
            if self.market == "US" and self.currency != "USD":
                raise ValueError("US security requires USD")
        if self.event_type in {"trade", "execution_aggregate"}:
            if self.side not in {"BUY", "SELL"} or self.quantity <= 0:
                raise ValueError("Trade requires side and positive quantity")
        if self.event_type == "security_transfer":
            if self.side not in {"IN", "OUT"} or self.quantity <= 0:
                raise ValueError("Transfer requires direction and positive quantity")
        if self.event_type == "fx_conversion":
            if self.counter_currency is None or self.counter_currency == self.currency:
                raise ValueError("FX requires a different counter currency")
        if self.event_type == "reversal" and self.revision == 1:
            raise ValueError("Reversal requires previous revision")
        return self


class LedgerBalance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    account_id: Identifier
    as_of: date
    source_record_hash: Digest
    cash_basis: Literal["settled"]
    cash: dict[Currency, Amount]
    receivables: dict[Currency, Amount]
    payables: dict[Currency, Amount]
    positions: dict[str, Amount]

    @model_validator(mode="after")
    def complete_balance(self):
        for name in ("cash", "receivables", "payables"):
            values = getattr(self, name)
            if set(values) != {"KRW", "USD"} or any(value < 0 for value in values.values()):
                raise ValueError("Explicit nonnegative balances for KRW and USD are required")
        for key, quantity in self.positions.items():
            if not re.fullmatch(r"(KR:[A-Z0-9.\-]+:KRW|US:[A-Z0-9.\-]+:USD)", key) or quantity < 0:
                raise ValueError(
                    "Position key must be market:symbol:currency; quantity nonnegative"
                )
        return self
