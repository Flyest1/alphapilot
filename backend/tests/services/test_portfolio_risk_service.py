from types import SimpleNamespace

import numpy as np
import pandas as pd

from app.models.settings import Settings
from app.services.portfolio_risk_service import PortfolioRiskService


def market_frame(periods=45, volume=1_000_000, multiplier=1.0):
    index = pd.date_range("2026-01-01", periods=periods, freq="B")
    close = (100 + np.arange(periods, dtype=float)) * multiplier
    return pd.DataFrame(
        {
            "open": close * 0.998,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": [volume] * periods,
        },
        index=index,
    )


def strategy(ticker, *, price=144, stop=130, target=170, detail=None):
    return SimpleNamespace(
        ticker=ticker,
        action="BUY",
        reasoning="candidate",
        current_price=price,
        stop_loss=stop,
        target_price=target,
        confidence_detail=detail or {},
    )


def row(ticker, *, market="KR", currency="KRW", frame=None, stale=False, sector=None):
    return {
        "asset": {
            "id": None,
            "ticker": ticker,
            "market": market,
            "currency": currency,
            "sector": sector,
        },
        "market_data": SimpleNamespace(
            dataframe=frame if frame is not None else market_frame(),
            is_stale=stale,
        ),
        "technical_analysis": SimpleNamespace(trend_label="strong bullish setup"),
    }


def portfolio(total=1_000_000, cash=1_000_000, allocation=None, sectors=None, currencies=None):
    return {
        "total_market_value": total,
        "cash_value": cash,
        "asset_allocation": allocation or [],
        "sector_exposure": sectors or [],
        "currency_exposure": currencies or [],
    }


def test_aggregate_candidates_deplete_portfolio_loss_budget_in_report_order():
    first = strategy("FIRST")
    second = strategy("SECOND")
    results, snapshot = PortfolioRiskService().calculate_position_sizing(
        strategies=[first, second],
        analysis_rows=[row("FIRST"), row("SECOND")],
        portfolio_summary=portfolio(),
        app_settings=Settings(usd_krw_rate=1400),
        owned_tickers=set(),
    )

    assert results["FIRST"]["suggested_max_amount"] == 102857
    assert results["SECOND"]["suggested_max_amount"] == 0
    assert results["SECOND"]["binding_constraint"] == "remaining_portfolio_loss"
    assert snapshot["remaining_loss_budget_amount"] == 0
    allocated_loss = sum(
        sizing["suggested_max_amount"] * sizing["risk_metrics"]["effective_downside_pct"] / 100
        for sizing in results.values()
    )
    assert allocated_loss <= snapshot["initial_loss_budget_amount"]
    assert snapshot["allocation_policy"] == "report_order_sequential"
    assert snapshot["candidate_order"] == ["FIRST", "SECOND"]


def test_low_return_history_keeps_stop_sizing_and_marks_volatility_unavailable():
    candidate = strategy(
        "SHORT",
        detail={
            "outcome_sample_size": 30,
            "target_hit_frequency": 0.6,
            "stop_hit_frequency": 0.2,
            "other_closed_frequency": 0.2,
        },
    )
    results, _ = PortfolioRiskService().calculate_position_sizing(
        strategies=[candidate],
        analysis_rows=[row("SHORT", frame=market_frame(periods=20))],
        portfolio_summary=portfolio(),
        app_settings=Settings(usd_krw_rate=1400),
        owned_tickers=set(),
    )

    sizing = results["SHORT"]
    assert sizing["suggested_max_amount"] > 0
    assert sizing["risk_metrics"]["volatility_status"] == "unavailable"
    assert sizing["risk_metrics"]["liquidity_status"] == "available"
    assert sizing["expected_value"]["status"] == "available"
    assert sizing["expected_value"]["other_frequency"] == 0.2
    assert sizing["expected_value"]["sample_size"] == 30


def test_ev_requires_closed_outcome_sample_and_negative_ev_binds_to_zero():
    low_sample = strategy("LOW", detail={"outcome_sample_size": 29})
    negative = strategy(
        "NEGATIVE",
        detail={
            "outcome_sample_size": 30,
            "target_hit_frequency": 0.1,
            "stop_hit_frequency": 0.8,
            "other_closed_frequency": 0.1,
        },
    )
    results, _ = PortfolioRiskService().calculate_position_sizing(
        strategies=[negative, low_sample],
        analysis_rows=[row("LOW"), row("NEGATIVE")],
        portfolio_summary=portfolio(),
        app_settings=Settings(usd_krw_rate=1400),
        owned_tickers=set(),
    )

    assert results["LOW"]["expected_value"]["status"] == "insufficient_sample"
    assert results["NEGATIVE"]["expected_value"]["status"] == "available"
    assert results["NEGATIVE"]["suggested_max_amount"] == 0
    assert results["NEGATIVE"]["binding_constraint"] == "expected_value"


def test_correlated_factor_constraint_binds_when_beta_and_correlation_are_available():
    held_frame = market_frame()
    candidate = strategy("CANDIDATE", price=144, stop=130)
    held = row("HELD", market="US", currency="USD", frame=held_frame)
    held["asset"]["id"] = "owned"
    allocation = [{"ticker": "HELD", "market": "US", "market_value": 500_000}]
    results, _ = PortfolioRiskService().calculate_position_sizing(
        strategies=[candidate],
        analysis_rows=[held, row("CANDIDATE", market="US", currency="USD", frame=held_frame)],
        portfolio_summary=portfolio(
            cash=500_000,
            allocation=allocation,
            currencies=[{"key": "USD", "value": 500_000}],
        ),
        app_settings=Settings(
            usd_krw_rate=1400,
            target_global_pct=100,
            target_domestic_pct=0,
            target_cash_pct=0,
            target_max_asset_pct=100,
            rebalance_band_pct=50,
        ),
        owned_tickers={"HELD"},
    )

    sizing = results["CANDIDATE"]
    assert sizing["constraints"]["beta"]["status"] == "available"
    assert sizing["constraints"]["correlated_factor"]["amount"] == 0
    assert sizing["binding_constraint"] == "correlated_factor"


def test_stale_and_non_finite_candidates_are_not_sized():
    stale = strategy("STALE")
    invalid = strategy("INVALID", price=float("nan"))
    results, snapshot = PortfolioRiskService().calculate_position_sizing(
        strategies=[stale, invalid],
        analysis_rows=[row("STALE", stale=True), row("INVALID")],
        portfolio_summary=portfolio(),
        app_settings=Settings(usd_krw_rate=1400),
        owned_tickers=set(),
    )

    assert results == {}
    assert snapshot["candidate_evaluations"] == [
        {"ticker": "STALE", "status": "excluded", "reason": "stale_market_data"},
        {"ticker": "INVALID", "status": "excluded", "reason": "invalid_current_price"},
    ]


def test_invalid_outcome_frequencies_do_not_produce_expected_value():
    candidate = strategy(
        "INVALID-EV",
        detail={
            "outcome_sample_size": 30,
            "target_hit_frequency": 0.8,
            "stop_hit_frequency": 0.4,
            "other_closed_frequency": 0.1,
        },
    )
    results, _ = PortfolioRiskService().calculate_position_sizing(
        strategies=[candidate],
        analysis_rows=[row("INVALID-EV")],
        portfolio_summary=portfolio(),
        app_settings=Settings(usd_krw_rate=1400),
        owned_tickers=set(),
    )

    assert results["INVALID-EV"]["expected_value"]["status"] == "insufficient_sample"


def test_incomplete_outcome_frequencies_do_not_produce_expected_value():
    candidate = strategy(
        "INCOMPLETE-EV",
        detail={
            "outcome_sample_size": 30,
            "target_hit_frequency": 0.5,
            "stop_hit_frequency": 0.2,
            "other_closed_frequency": 0.1,
        },
    )
    results, _ = PortfolioRiskService().calculate_position_sizing(
        strategies=[candidate],
        analysis_rows=[row("INCOMPLETE-EV")],
        portfolio_summary=portfolio(),
        app_settings=Settings(usd_krw_rate=1400),
        owned_tickers=set(),
    )

    assert results["INCOMPLETE-EV"]["expected_value"]["status"] == "insufficient_sample"


def test_krw_candidate_does_not_use_usd_cash_without_fx_model():
    candidate = strategy("KRW-CANDIDATE")
    results, snapshot = PortfolioRiskService().calculate_position_sizing(
        strategies=[candidate],
        analysis_rows=[row("KRW-CANDIDATE")],
        portfolio_summary=portfolio(
            cash=1_000_000,
            allocation=[
                {
                    "ticker": "USD",
                    "market": "CASH",
                    "currency": "USD",
                    "market_value": 1_000_000,
                }
            ],
            currencies=[{"key": "USD", "value": 1_000_000}],
        ),
        app_settings=Settings(usd_krw_rate=1400),
        owned_tickers=set(),
    )

    assert results["KRW-CANDIDATE"]["suggested_max_amount"] == 0
    assert results["KRW-CANDIDATE"]["binding_constraint"] == "remaining_cash"
    assert snapshot["initial_cash_by_currency"] == {"USD": 200000}


def test_partial_held_asset_context_disables_beta_and_correlation_constraints():
    candidate = strategy("CANDIDATE")
    held = row("HELD", frame=market_frame())
    held["asset"]["id"] = "owned"
    results, snapshot = PortfolioRiskService().calculate_position_sizing(
        strategies=[candidate],
        analysis_rows=[held, row("CANDIDATE", frame=market_frame())],
        portfolio_summary=portfolio(
            allocation=[
                {"ticker": "HELD", "market": "KR", "market_value": 300_000},
                {"ticker": "MISSING", "market": "US", "market_value": 300_000},
            ]
        ),
        app_settings=Settings(usd_krw_rate=1400),
        owned_tickers={"HELD", "MISSING"},
    )

    sizing = results["CANDIDATE"]
    assert sizing["constraints"]["beta"]["status"] == "unavailable"
    assert sizing["constraints"]["correlated_factor"]["status"] == "unavailable"
    assert sizing["correlation_metrics"]["status"] == "partial"
    assert snapshot["risk_context_status"] == "partial"
    assert snapshot["missing_held_assets"] == [{"market": "US", "ticker": "MISSING"}]
