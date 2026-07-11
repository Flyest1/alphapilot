import pytest

from app.services.backtest_metrics import (
    UNKNOWN_LIQUIDITY_SLIPPAGE_PCT,
    calculate_backtest_metrics,
    estimate_liquidity_slippage_pct,
    estimate_round_trip_cost_pct,
)


def test_round_trip_cost_applies_same_convention_to_all_actions() -> None:
    results = [
        estimate_round_trip_cost_pct(
            action=action,
            market="KR",
            fee_rate_pct=0.1,
            kr_tax_rate_pct=0.18,
            fx_spread_pct=0.4,
            average_trading_value=20_000_000_000,
        )
        for action in ("BUY", "HOLD", "WATCH", "SELL", "REDUCE")
    ]

    assert all(result == results[0] for result in results)
    assert results[0] == {
        "fee_pct": 0.2,
        "kr_tax_pct": 0.18,
        "fx_spread_pct": 0.0,
        "slippage_pct": 0.08,
        "total_cost_pct": 0.46,
    }


def test_us_cost_uses_round_trip_fx_spread_without_kr_tax() -> None:
    result = estimate_round_trip_cost_pct(
        action="BUY",
        market="US",
        fee_rate_pct=0.05,
        kr_tax_rate_pct=0.18,
        fx_spread_pct=0.4,
        average_trading_value=2_000_000_000,
    )

    assert result["fee_pct"] == 0.1
    assert result["kr_tax_pct"] == 0.0
    assert result["fx_spread_pct"] == 0.8
    assert result["slippage_pct"] == 0.15
    assert result["total_cost_pct"] == 1.05


def test_unknown_and_low_liquidity_receive_conservative_slippage() -> None:
    assert estimate_liquidity_slippage_pct(None) == UNKNOWN_LIQUIDITY_SLIPPAGE_PCT
    assert estimate_liquidity_slippage_pct(float("nan")) == UNKNOWN_LIQUIDITY_SLIPPAGE_PCT
    assert estimate_liquidity_slippage_pct(50_000_000) > UNKNOWN_LIQUIDITY_SLIPPAGE_PCT
    assert estimate_liquidity_slippage_pct(50_000_000) > estimate_liquidity_slippage_pct(
        20_000_000_000
    )


def test_cost_rejects_unsupported_action() -> None:
    with pytest.raises(ValueError, match="Unsupported recommendation action"):
        estimate_round_trip_cost_pct(
            action="EXECUTE",
            market="KR",
            fee_rate_pct=0.1,
            kr_tax_rate_pct=0.18,
            fx_spread_pct=0.0,
        )


def test_calculate_metrics_reports_gross_net_risk_and_tail_metrics() -> None:
    samples = [
        {
            "date": "2025-01-02",
            "gross_return_pct": 10.0,
            "net_return_pct": 9.0,
            "turnover": 1.5,
        },
        {
            "date": "2025-02-03",
            "gross_return_pct": -5.0,
            "net_return_pct": -6.0,
            "turnover": 1.0,
        },
        {
            "date": "2025-04-01",
            "gross_return_pct": 4.0,
            "net_return_pct": 3.0,
            "turnover": 0.5,
        },
        {
            "date": "2026-01-02",
            "gross_return_pct": -2.0,
            "net_return_pct": -3.0,
            "turnover": 1.0,
        },
    ]

    result = calculate_backtest_metrics(samples)

    assert result["sample_count"] == 4
    assert result["start_date"] == "2025-01-02"
    assert result["end_date"] == "2026-01-02"
    assert result["gross"]["cumulative_return_pct"] == pytest.approx(6.5064)
    assert result["net"]["cumulative_return_pct"] == pytest.approx(2.367786)
    assert result["gross"]["annualized_return_pct"] == pytest.approx(6.510998, abs=1e-6)
    assert result["gross"]["sharpe"] is not None
    assert result["gross"]["sortino"] is not None
    assert result["gross"]["calmar"] is not None
    assert result["gross"]["max_drawdown_pct"] == pytest.approx(-5.0)
    assert result["gross"]["recovery_days"] is None
    assert result["gross"]["hit_rate"] == 0.5
    assert result["gross"]["average_gain_pct"] == 7.0
    assert result["gross"]["average_loss_pct"] == -3.5
    assert result["gross"]["expectancy_pct"] == 1.75
    assert result["gross"]["profit_factor"] == 2.0
    assert result["gross"]["worst_month"] == {"period": "2025-02", "return_pct": -5.0}
    assert result["gross"]["worst_quarter"] == {"period": "2026Q1", "return_pct": -2.0}
    assert result["gross"]["bottom_10pct_average_pct"] == -5.0
    assert result["turnover"]["total"] == 4.0
    assert result["turnover"]["annualized"] == pytest.approx(4.00274, abs=1e-6)
    assert result["recommendation_frequency"]["annualized"] == pytest.approx(4.00274, abs=1e-6)
    assert result["recommendation_frequency"]["per_active_month"] == 1.0


def test_empty_samples_return_safe_defaults() -> None:
    result = calculate_backtest_metrics([])

    assert result["sample_count"] == 0
    assert result["gross"]["cumulative_return_pct"] == 0.0
    assert result["gross"]["annualized_return_pct"] is None
    assert result["gross"]["sharpe"] is None
    assert result["gross"]["max_drawdown_pct"] == 0.0
    assert result["gross"]["bottom_10pct_average_pct"] is None
    assert result["turnover"] == {"total": 0.0, "annualized": None}


def test_single_sample_uses_safe_non_annualized_metrics_and_default_turnover() -> None:
    result = calculate_backtest_metrics(
        [{"date": "2025-01-02", "gross_return_pct": 5.0, "net_return_pct": 4.0}]
    )

    assert result["gross"]["cumulative_return_pct"] == 5.0
    assert result["gross"]["annualized_return_pct"] is None
    assert result["gross"]["sharpe"] is None
    assert result["gross"]["sortino"] is None
    assert result["gross"]["calmar"] is None
    assert result["gross"]["recovery_days"] == 0
    assert result["turnover"] == {"total": 2.0, "annualized": None}
    assert result["recommendation_frequency"] == {
        "annualized": None,
        "per_active_month": 1.0,
    }


def test_all_losses_and_zero_variance_are_safe() -> None:
    losses = calculate_backtest_metrics(
        [
            {"date": "2025-01-02", "gross_return_pct": -2.0, "net_return_pct": -3.0},
            {"date": "2026-01-02", "gross_return_pct": -2.0, "net_return_pct": -3.0},
        ]
    )
    flat_variance = calculate_backtest_metrics(
        [
            {"date": "2025-01-02", "gross_return_pct": 2.0, "net_return_pct": 1.0},
            {"date": "2026-01-02", "gross_return_pct": 2.0, "net_return_pct": 1.0},
        ]
    )

    assert losses["gross"]["hit_rate"] == 0.0
    assert losses["gross"]["average_gain_pct"] is None
    assert losses["gross"]["average_loss_pct"] == -2.0
    assert losses["gross"]["profit_factor"] == 0.0
    assert losses["gross"]["sharpe"] is None
    assert flat_variance["gross"]["sharpe"] is None
    assert flat_variance["gross"]["sortino"] is None
    assert flat_variance["gross"]["calmar"] is None
    assert flat_variance["gross"]["max_drawdown_pct"] == 0.0


def test_input_contract_rejects_missing_and_non_finite_values() -> None:
    with pytest.raises(ValueError, match="missing required fields"):
        calculate_backtest_metrics([{"date": "2025-01-02", "gross_return_pct": 1.0}])
    with pytest.raises(ValueError, match="non-finite net_return_pct"):
        calculate_backtest_metrics(
            [
                {
                    "date": "2025-01-02",
                    "gross_return_pct": 1.0,
                    "net_return_pct": float("inf"),
                }
            ]
        )

    with pytest.raises(ValueError, match="greater than -100"):
        calculate_backtest_metrics(
            [{"date": "2025-01-02", "gross_return_pct": -100, "net_return_pct": -101}]
        )
