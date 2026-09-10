"""Offline simulation tests; no broker requests or credentials."""

from decimal import Decimal as D

import pytest

from app.services.execution_simulation import (
    ExecutionSimulation,
    SimulationEvent,
    SimulationIntent,
    SimulationLimits,
)


def simulator():
    return ExecutionSimulation(SimulationLimits(D("1000"), D("600"), D("800"), D("50")), D("0"))


def intent(key="one", quantity="5", price="100"):
    return SimulationIntent(key, "TEST", D(quantity), D(price))


def test_duplicate_intent_and_event_cannot_double_count_or_release_fills():
    sim = simulator()
    original = sim.submit(intent())
    assert original.state == "acknowledged"
    assert original.simulated is True
    assert sim.submit(intent()) == original
    partial = SimulationEvent("fill1", "partial", D("2"), D("190"))
    sim.apply("one", partial)
    assert sim.apply("one", partial).filled_quantity == D("2")
    assert sim.committed_amount == D("490")
    cancelled = sim.apply("one", SimulationEvent("cancel", "cancelled", D("2"), D("190")))
    assert cancelled.filled_notional == D("190")
    assert sim.committed_amount == D("490")
    late = sim.apply("one", SimulationEvent("late-fill", "partial", D("3"), D("285")))
    assert late.state == "cancelled"
    assert late.filled_quantity == D("3")
    assert sim.committed_amount == D("485")


def test_unknown_keeps_reservation_and_cannot_be_resubmitted():
    sim = simulator()
    sim.submit(intent())
    unknown = sim.apply("one", SimulationEvent("timeout", "unknown", D("0"), D("0")))
    assert sim.submit(intent()) == unknown
    assert sim.committed_amount == D("500")
    assert sim.submit(intent("two")).state == "rejected"
    with pytest.raises(ValueError):
        sim.submit(intent(quantity="4"))


def test_missing_configuration_loss_limit_and_kill_switch_fail_closed():
    assert ExecutionSimulation(None, None).submit(intent()).state == "rejected"
    sim = simulator()
    sim.set_kill_switch(True)
    assert sim.submit(intent()).state == "rejected"
    limits = SimulationLimits(D("1000"), D("600"), D("800"), D("50"))
    assert ExecutionSimulation(limits, D("50")).submit(intent()).state == "rejected"


def test_loss_reduces_available_capital_and_order_limit_is_enforced():
    limits = SimulationLimits(D("500"), D("500"), D("500"), D("50"))
    assert ExecutionSimulation(limits, D("10")).submit(intent()).state == "rejected"
    assert simulator().submit(intent(quantity="7")).reason == "order_limit"


def test_kill_switch_blocks_new_intents_but_allows_reconciling_prior_fills():
    sim = simulator()
    sim.submit(intent())
    sim.set_kill_switch(True)
    assert sim.submit(intent("two")).state == "rejected"
    assert sim.apply("one", SimulationEvent("fill", "filled", D("5"), D("500"))).state == "filled"


def test_cancel_does_not_release_reservation_before_late_fill_finality():
    sim = simulator()
    sim.submit(intent())
    sim.apply("one", SimulationEvent("cancel", "cancelled", D("0"), D("0")))
    assert sim.submit(intent("two", quantity="6")).state == "rejected"
    final = sim.apply("one", SimulationEvent("late", "filled", D("5"), D("500")))
    assert final.state == "filled"
    assert sim.committed_amount == D("500")


def test_external_loss_breach_is_explicit_and_stops_new_intents_without_dropping_fills():
    sim = simulator()
    sim.submit(intent())
    sim.update_observed_loss(D("600"))
    assert sim.risk_breached is True
    assert sim.kill_switch_enabled is True
    assert sim.submit(intent("two", quantity="1")).state == "rejected"
    assert sim.apply("one", SimulationEvent("fill", "filled", D("5"), D("500"))).state == "filled"
    with pytest.raises(ValueError):
        sim.set_kill_switch(False)


@pytest.mark.parametrize(
    "event",
    [
        SimulationEvent("bad", "filled", D("6"), D("600")),
        SimulationEvent("bad", "filled", D("2"), D("200")),
        SimulationEvent("bad", "partial", D("2"), D("201")),
        SimulationEvent("bad", "partial", D("-1"), D("0")),
    ],
)
def test_invalid_events_leave_state_unchanged(event):
    sim = simulator()
    previous = sim.submit(intent())
    with pytest.raises(ValueError):
        sim.apply("one", event)
    assert sim.get("one") == previous


def test_event_identity_conflict_and_stale_fills_are_rejected_without_mutation():
    sim = simulator()
    sim.submit(intent())
    previous = sim.apply("one", SimulationEvent("event", "partial", D("2"), D("190")))
    for event in (
        SimulationEvent("event", "partial", D("3"), D("285")),
        SimulationEvent("older", "partial", D("1"), D("95")),
    ):
        with pytest.raises(ValueError):
            sim.apply("one", event)
        assert sim.get("one") == previous


def test_filled_order_cannot_be_cancelled_and_decimal_inputs_are_required():
    sim = simulator()
    sim.submit(intent())
    final = sim.apply("one", SimulationEvent("fill", "filled", D("5"), D("475")))
    with pytest.raises(ValueError):
        sim.apply("one", SimulationEvent("cancel", "cancelled", D("5"), D("475")))
    assert sim.get("one") == final
    with pytest.raises(ValueError):
        sim.submit(SimulationIntent("float", "TEST", 0.1, D("100")))


def test_replayed_event_sequence_is_deterministic():
    events = [
        SimulationEvent("1", "unknown", D("0"), D("0")),
        SimulationEvent("2", "acknowledged", D("0"), D("0")),
        SimulationEvent("3", "partial", D("1"), D("95")),
        SimulationEvent("4", "filled", D("5"), D("475")),
    ]
    states = []
    for _ in range(2):
        sim = simulator()
        sim.submit(intent())
        for event in events + events:
            sim.apply("one", event)
        states.append(sim.get("one"))
    assert states[0] == states[1]


def test_incremental_fill_cannot_hide_above_limit_price_in_cumulative_average():
    sim = simulator()
    sim.submit(intent())
    previous = sim.apply("one", SimulationEvent("cheap", "partial", D("1"), D("50")))
    with pytest.raises(ValueError):
        sim.apply("one", SimulationEvent("expensive", "partial", D("2"), D("200")))
    assert sim.get("one") == previous


def test_full_fill_evidence_on_cancel_is_still_filled():
    sim = simulator()
    sim.submit(intent())
    result = sim.apply("one", SimulationEvent("cancel", "cancelled", D("5"), D("500")))
    assert result.state == "filled"


def test_decimal_arithmetic_does_not_depend_on_callers_low_precision_context():
    from decimal import localcontext

    sim = simulator()
    with localcontext() as context:
        context.prec = 3
        sim.submit(intent(quantity="1.23456789", price="12.3456789"))
        assert sim.committed_amount == D("15.241578750190521")
