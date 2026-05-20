from types import SimpleNamespace

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
