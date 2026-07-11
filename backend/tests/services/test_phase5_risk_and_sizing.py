"""Phase 5: ATR 기반 손절/목표, 목표 배분 드리프트, 포지션 사이징, 비용 차감 수익률."""

from types import SimpleNamespace

import pandas as pd

from app.db.supabase_client import InMemoryRepository
from app.services.portfolio_service import PortfolioService
from app.services.strategy_service import StrategyService
from app.services.technical_analysis_service import TechnicalAnalysisService


def asset():
    return {
        "id": "asset-1",
        "market": "US",
        "ticker": "AAPL",
        "name": "Apple",
        "quantity": 2,
        "avg_price": 100,
    }


def technical(score=82, atr=None):
    indicators = {"rsi_14": 60}
    if atr is not None:
        indicators["atr_14"] = atr
    return SimpleNamespace(
        technical_score=score,
        trend_label="strong bullish setup",
        indicators=indicators,
    )


def test_atr_indicator_is_calculated():
    index = pd.date_range("2026-01-01", periods=60, freq="B")
    frame = pd.DataFrame(
        {
            "open": [100.0] * 60,
            "high": [105.0] * 60,
            "low": [95.0] * 60,
            "close": [100.0] * 60,
            "volume": [1000] * 60,
        },
        index=index,
    )

    result = TechnicalAnalysisService().analyze("TEST", frame)

    # 고저폭이 매일 10이므로 ATR(14)은 10에 수렴한다.
    assert result.indicators["atr_14"] is not None
    assert abs(result.indicators["atr_14"] - 10) < 0.5


def test_atr_based_stop_and_target_by_risk_profile():
    service = StrategyService()
    market = SimpleNamespace(is_stale=False, current_price=100)

    balanced = service.generate_strategy(asset(), market, technical(atr=4), "balanced")
    aggressive = service.generate_strategy(asset(), market, technical(atr=4), "aggressive")

    assert balanced.stop_loss == 92  # 100 − 2.0×4
    assert balanced.target_price == 112  # 100 + 3.0×4
    assert aggressive.stop_loss == 90  # 100 − 2.5×4
    assert aggressive.target_price == 116  # 100 + 4.0×4
    assert "ATR(14)" in balanced.risk
    assert "92.0000" in balanced.invalidation_condition


def test_missing_or_degenerate_atr_falls_back_to_fixed_percent():
    service = StrategyService()
    market = SimpleNamespace(is_stale=False, current_price=100)

    without_atr = service.generate_strategy(asset(), market, technical(atr=None), "balanced")
    extreme_atr = service.generate_strategy(asset(), market, technical(atr=50), "balanced")

    assert without_atr.stop_loss == 92  # 100 × (1 − 0.08)
    assert without_atr.target_price == 112  # 100 × (1 + 0.12)
    assert "ATR(14)" not in without_atr.risk
    assert extreme_atr.stop_loss == 92  # ATR 비율 20% 초과 → 폴백


def test_reduce_action_uses_directional_target_and_stop_with_atr():
    service = StrategyService()
    market = SimpleNamespace(is_stale=False, current_price=100)

    reduce_strategy = service.generate_strategy(
        asset(), market, technical(score=40, atr=4), "balanced"
    )

    assert reduce_strategy.action == "REDUCE"
    assert reduce_strategy.target_price == 96  # 100 - 1×ATR
    assert reduce_strategy.stop_loss == 108  # 100 + 2×ATR


def seed_portfolio(repo):
    repo.upsert_settings({"usd_krw_rate": 1000})
    repo.create_asset(
        {
            "market": "KR",
            "ticker": "005930",
            "name": "Samsung",
            "quantity": 7,
            "avg_price": 100000,
            "currency": "KRW",
        }
    )
    repo.create_asset(
        {
            "market": "CASH",
            "ticker": "KRW",
            "name": "현금",
            "quantity": 1,
            "avg_price": 300000,
            "currency": "KRW",
        }
    )


def test_allocation_drift_rows_and_suggestions():
    repo = InMemoryRepository()
    seed_portfolio(repo)
    # 목표: 국내 40 / 글로벌 40 / 현금 20. 실제: 국내 70 / 글로벌 0 / 현금 30.

    summary = PortfolioService(repo).get_summary()
    drift = {row["key"]: row for row in summary.allocation_drift}

    assert drift["domestic"]["actual_pct"] == 70
    assert drift["domestic"]["drift_pct"] == 30
    assert drift["domestic"]["exceeded"] is True
    assert drift["global"]["drift_pct"] == -40
    assert drift["cash"]["drift_pct"] == 10
    assert any("국내" in text and "축소" in text for text in summary.rebalance_suggestions)
    assert any("글로벌" in text and "확대" in text for text in summary.rebalance_suggestions)
    assert any("현금" in text and "분할 매수" in text for text in summary.rebalance_suggestions)


def test_drift_respects_custom_targets_and_band():
    repo = InMemoryRepository()
    seed_portfolio(repo)
    repo.upsert_settings(
        {
            "usd_krw_rate": 1000,
            "target_domestic_pct": 70,
            "target_global_pct": 0,
            "target_cash_pct": 30,
            "rebalance_band_pct": 5,
        }
    )

    summary = PortfolioService(repo).get_summary()

    assert summary.rebalance_suggestions == []
    assert all(row["exceeded"] is False for row in summary.allocation_drift)


def test_net_returns_subtract_fees_taxes_and_fx_spread():
    repo = InMemoryRepository()
    repo.upsert_settings(
        {
            "usd_krw_rate": 1000,
            "fee_rate_pct": 0.1,
            "kr_tax_rate_pct": 0.2,
            "fx_spread_pct": 0.5,
        }
    )
    repo.create_asset(
        {
            "market": "KR",
            "ticker": "005930",
            "name": "Samsung",
            "quantity": 1,
            "avg_price": 100000,
            "currency": "KRW",
        }
    )
    repo.create_asset(
        {
            "market": "US",
            "ticker": "AAPL",
            "name": "Apple",
            "quantity": 1,
            "avg_price": 100,
            "currency": "USD",
        }
    )

    summary = PortfolioService(repo).get_summary()
    rows = {row["ticker"]: row for row in summary.asset_returns}

    # KR: 매수 수수료 0.1% × 100,000 + 매도 (0.1% + 0.2%) × 100,000 = 100 + 300 = 400
    assert rows["005930"]["estimated_costs"] == 400
    assert rows["005930"]["net_profit_loss"] == -400
    assert rows["005930"]["net_return_rate"] == -0.4
    # US: 매수 (0.1+0.5)% × 100,000 + 매도 (0.1+0.5)% × 100,000 = 1,200
    assert rows["AAPL"]["estimated_costs"] == 1200
    assert summary.total_net_profit_loss == -1600
    assert summary.total_net_return_rate == -0.8
