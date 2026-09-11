"""Isolated cash-funded BUY lifecycle simulation, never a broker adapter.

No network, credentials, clocks, persistence, routes, or scheduling. Quantities and
amounts are synthetic and denominated in one caller-selected currency. This does
not claim Toss supports these event names or client-side idempotency. A future
adapter must reconcile its official contract separately. Unknown and cancelled
outcomes retain their unfilled reservation: this harness has no broker finality
proof or release operation. Submitting the same intent only reads its state.
"""

from dataclasses import dataclass, replace
from decimal import Context, Decimal, Inexact, localcontext
from functools import wraps

ZERO = Decimal("0")
STATES = {"rejected", "acknowledged", "partial", "filled", "cancelled", "unknown"}


def _exact(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with localcontext(Context(prec=64)) as context:
            context.traps[Inexact] = True
            return function(*args, **kwargs)

    return wrapped


def _decimal(value: Decimal, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("Finite Decimal required")
    if value < ZERO or (positive and value == ZERO):
        raise ValueError("Invalid nonnegative amount or quantity")


@dataclass(frozen=True)
class SimulationLimits:
    capital: Decimal
    max_order_notional: Decimal
    max_committed_notional: Decimal
    max_loss: Decimal

    def __post_init__(self) -> None:
        for value in (
            self.capital,
            self.max_order_notional,
            self.max_committed_notional,
            self.max_loss,
        ):
            _decimal(value, positive=True)
        if self.max_committed_notional > self.capital:
            raise ValueError("Committed limit exceeds configured capital")


@dataclass(frozen=True)
class SimulationIntent:
    client_intent_id: str
    ticker: str
    quantity: Decimal
    limit_price: Decimal


@dataclass(frozen=True)
class SimulationEvent:
    event_id: str
    state: str
    cumulative_quantity: Decimal
    cumulative_notional: Decimal


@dataclass(frozen=True)
class SimulatedOrder:
    intent: SimulationIntent
    state: str
    filled_quantity: Decimal = ZERO
    filled_notional: Decimal = ZERO
    reason: str | None = None
    simulated: bool = True


class ExecutionSimulation:
    """A deterministic test harness; all configuration has to be supplied explicitly."""

    def __init__(self, limits: SimulationLimits | None, observed_loss: Decimal | None):
        if observed_loss is not None:
            _decimal(observed_loss)
        self._limits = limits
        self._observed_loss = observed_loss
        self._kill_switch = False
        self._orders: dict[str, SimulatedOrder] = {}
        self._events: dict[tuple[str, str], SimulationEvent] = {}

    def set_kill_switch(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise ValueError("Explicit boolean required")
        if not enabled and self.risk_breached:
            raise ValueError("Cannot disable kill switch while risk is breached")
        self._kill_switch = enabled

    @property
    def kill_switch_enabled(self) -> bool:
        return self._kill_switch

    @property
    @_exact
    def risk_breached(self) -> bool:
        if self._limits is None or self._observed_loss is None:
            return True
        return self._observed_loss >= self._limits.max_loss or self.committed_amount > min(
            max(ZERO, self._limits.capital - self._observed_loss),
            self._limits.max_committed_notional,
        )

    def update_observed_loss(self, observed_loss: Decimal | None) -> None:
        if observed_loss is not None:
            _decimal(observed_loss)
        self._observed_loss = observed_loss
        if self.risk_breached:
            self._kill_switch = True

    def get(self, client_intent_id: str) -> SimulatedOrder:
        return self._orders[client_intent_id]

    @property
    @_exact
    def committed_amount(self) -> Decimal:
        total = ZERO
        for order in self._orders.values():
            total += order.filled_notional
            if order.state in {"acknowledged", "partial", "unknown", "cancelled"}:
                total += (order.intent.quantity - order.filled_quantity) * order.intent.limit_price
        return total

    @_exact
    def submit(self, intent: SimulationIntent) -> SimulatedOrder:
        if not intent.client_intent_id.strip() or not intent.ticker.strip():
            raise ValueError("Intent identity and ticker required")
        _decimal(intent.quantity, positive=True)
        _decimal(intent.limit_price, positive=True)
        existing = self._orders.get(intent.client_intent_id)
        if existing is not None:
            if existing.intent != intent:
                raise ValueError("Intent identity reused with different payload")
            return existing
        limits = self._limits
        amount = intent.quantity * intent.limit_price
        reason = None
        if limits is None or self._observed_loss is None:
            reason = "risk_configuration_missing"
        elif self._kill_switch:
            reason = "kill_switch"
        elif self._observed_loss >= limits.max_loss:
            reason = "loss_limit"
        elif amount > limits.max_order_notional:
            reason = "order_limit"
        elif self.committed_amount + amount > min(
            max(ZERO, limits.capital - self._observed_loss), limits.max_committed_notional
        ):
            reason = "committed_limit"
        order = SimulatedOrder(intent, "rejected" if reason else "acknowledged", reason=reason)
        self._orders[intent.client_intent_id] = order
        return order

    @_exact
    def apply(self, client_intent_id: str, event: SimulationEvent) -> SimulatedOrder:
        """Apply explicit synthetic reconciliation evidence, never infer a retry."""
        order = self.get(client_intent_id)
        if not event.event_id.strip() or event.state not in STATES:
            raise ValueError("Valid event identity and state required")
        event_key = (client_intent_id, event.event_id)
        previous = self._events.get(event_key)
        if previous is not None:
            if previous != event:
                raise ValueError("Event identity reused with different payload")
            return order
        _decimal(event.cumulative_quantity)
        _decimal(event.cumulative_notional)
        quantity, amount = event.cumulative_quantity, event.cumulative_notional
        if order.state in {"rejected", "filled"}:
            raise ValueError("Terminal order cannot transition")
        if not order.filled_quantity <= quantity <= order.intent.quantity:
            raise ValueError("Cumulative fills regress or exceed intent")
        if amount < order.filled_notional or amount > quantity * order.intent.limit_price:
            raise ValueError("Cumulative notional invalid")
        if (quantity == ZERO) != (amount == ZERO):
            raise ValueError("Fill quantity and notional inconsistent")
        if quantity == order.filled_quantity and amount != order.filled_notional:
            raise ValueError("Notional changed without new fills")
        quantity_delta = quantity - order.filled_quantity
        amount_delta = amount - order.filled_notional
        if (
            quantity_delta > ZERO
            and not ZERO < amount_delta <= quantity_delta * order.intent.limit_price
        ):
            raise ValueError("Incremental fill violates positive limit-price execution")
        if event.state in {"acknowledged", "rejected"} and quantity != ZERO:
            raise ValueError("State cannot erase fills")
        if event.state == "filled" and quantity != order.intent.quantity:
            raise ValueError("Filled state requires full quantity")
        if event.state == "partial" and not ZERO < quantity < order.intent.quantity:
            raise ValueError("Partial state requires partial quantity")
        state = "filled" if quantity == order.intent.quantity else event.state
        if order.state == "cancelled":
            if state not in {"partial", "filled", "cancelled"}:
                raise ValueError("Cancelled order cannot be reopened")
            state = "filled" if quantity == order.intent.quantity else "cancelled"
        updated = replace(order, state=state, filled_quantity=quantity, filled_notional=amount)
        self._orders[client_intent_id] = updated
        self._events[event_key] = event
        return updated
