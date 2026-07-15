from types import SimpleNamespace

import pytest

from app.services.strategy_service import StrategyService


def asset():
    return {
        "id": "asset-1",
        "market": "US",
        "ticker": "AAPL",
        "name": "Apple",
        "quantity": 2,
        "avg_price": 100,
    }


def test_stale_data_produces_watch_strategy():
    strategy = StrategyService().generate_strategy(
        asset(),
        SimpleNamespace(is_stale=True, current_price=None),
        SimpleNamespace(technical_score=90, trend_label="strong"),
        "balanced",
    )

    assert strategy.action == "WATCH"
    assert strategy.confidence == 0
    assert strategy.reasoning == "data-limited"


def test_populates_required_strategy_fields_for_fresh_data():
    strategy = StrategyService().generate_strategy(
        asset(),
        SimpleNamespace(is_stale=False, current_price=120),
        SimpleNamespace(technical_score=82, trend_label="strong bullish setup"),
        "balanced",
    )

    assert strategy.action == "BUY"
    assert strategy.confidence == 82
    assert strategy.buy_range_low is not None
    assert strategy.target_price is not None
    assert strategy.stop_loss is not None
    assert strategy.risk
    assert strategy.invalidation_condition


def test_risk_profile_affects_output():
    service = StrategyService()
    conservative = service.generate_strategy(
        asset(),
        SimpleNamespace(is_stale=False, current_price=100),
        SimpleNamespace(technical_score=82, trend_label="strong bullish setup"),
        "conservative",
    )
    aggressive = service.generate_strategy(
        asset(),
        SimpleNamespace(is_stale=False, current_price=100),
        SimpleNamespace(technical_score=82, trend_label="strong bullish setup"),
        "aggressive",
    )

    assert conservative.action == "HOLD"
    assert aggressive.action == "BUY"
    assert conservative.stop_loss > aggressive.stop_loss


@pytest.mark.parametrize(
    ("risk_profile", "score", "expected"),
    [
        ("balanced", 34, "SELL"),
        ("balanced", 35, "REDUCE"),
        ("balanced", 49, "REDUCE"),
        ("balanced", 50, "WATCH"),
        ("balanced", 64, "WATCH"),
        ("balanced", 65, "HOLD"),
        ("balanced", 79, "HOLD"),
        ("balanced", 80, "BUY"),
        ("conservative", 65, "HOLD"),
        ("conservative", 80, "HOLD"),
        ("aggressive", 65, "BUY"),
        ("aggressive", 80, "BUY"),
    ],
)
def test_action_for_score_preserves_profile_boundaries(risk_profile, score, expected):
    assert StrategyService.action_for_score(score, risk_profile) == expected


@pytest.mark.parametrize("score", [20, 40, 55, 70, 90])
def test_generated_strategy_uses_public_action_mapping(score):
    strategy = StrategyService().generate_strategy(
        asset(),
        SimpleNamespace(is_stale=False, current_price=100),
        SimpleNamespace(technical_score=score, trend_label="watch"),
        "balanced",
    )

    assert strategy.action == StrategyService.action_for_score(score, "balanced")


@pytest.mark.parametrize("score", [20, 40])
@pytest.mark.parametrize("atr", [None, 5])
def test_sell_and_reduce_prices_follow_short_direction(score, atr):
    indicators = {} if atr is None else {"atr_14": atr}
    strategy = StrategyService().generate_strategy(
        asset(),
        SimpleNamespace(is_stale=False, current_price=100),
        SimpleNamespace(technical_score=score, trend_label="weak", indicators=indicators),
        "balanced",
    )

    assert strategy.target_price < strategy.current_price < strategy.stop_loss


@pytest.mark.parametrize("score", [55, 70, 90])
@pytest.mark.parametrize("atr", [None, 5])
def test_buy_hold_and_watch_prices_follow_long_direction(score, atr):
    indicators = {} if atr is None else {"atr_14": atr}
    strategy = StrategyService().generate_strategy(
        asset(),
        SimpleNamespace(is_stale=False, current_price=100),
        SimpleNamespace(technical_score=score, trend_label="strong", indicators=indicators),
        "balanced",
    )

    assert strategy.stop_loss < strategy.current_price < strategy.target_price


def test_data_limited_technical_analysis_forces_watch():
    strategy = StrategyService().generate_strategy(
        asset(),
        SimpleNamespace(is_stale=False, current_price=100),
        SimpleNamespace(
            technical_score=0,
            trend_label="data-limited",
            data_quality_note="insufficient market data",
            indicators={},
        ),
        "balanced",
    )

    assert strategy.action == "WATCH"
    assert strategy.confidence == 0
    assert strategy.reasoning == "data-limited"


def test_non_finite_market_price_forces_data_limited_watch():
    strategy = StrategyService().generate_strategy(
        asset(),
        SimpleNamespace(is_stale=False, current_price=float("nan")),
        SimpleNamespace(technical_score=80, trend_label="strong bullish setup", indicators={}),
        "balanced",
    )

    assert strategy.action == "WATCH"
    assert strategy.confidence == 0
