from datetime import datetime, timezone

import pandas as pd

from app.services.advisory.features.profit_taking_review import ProfitTakingReviewService
from app.services.market_data_service import MarketDataResult
from app.models.advisory import validate_advisory_result
from app.services.technical_analysis_service import TechnicalAnalysisResult


def statement(rows):
    return pd.DataFrame(
        rows,
        columns=[pd.Timestamp("2026-06-30"), pd.Timestamp("2026-03-31")],
    )


def market_data(current_price=120):
    index = pd.date_range("2026-01-01", periods=130, freq="B")
    frame = pd.DataFrame(
        {
            "open": [current_price] * 130,
            "high": [current_price + 1] * 130,
            "low": [current_price - 1] * 130,
            "close": [current_price] * 130,
            "volume": [1000] * 130,
        },
        index=index,
    )
    return MarketDataResult(
        dataframe=frame,
        last_trading_date=index[-1].to_pydatetime().replace(tzinfo=timezone.utc),
        is_stale=False,
        provider="yfinance",
        data_quality_note="ok",
        current_price=current_price,
    )


class FakeMarketData:
    def __init__(self, result):
        self.result = result

    def fetch_price_history(self, *_args):
        return self.result


class FullTicker:
    info = {"longName": "Example", "forwardPE": 20, "trailingPE": 22}
    quarterly_financials = statement(
        {
            pd.Timestamp("2026-06-30"): {"Total Revenue": 120, "Operating Income": 24},
            pd.Timestamp("2026-03-31"): {"Total Revenue": 100, "Operating Income": 15},
        }
    )
    quarterly_cashflow = statement(
        {
            pd.Timestamp("2026-06-30"): {"Free Cash Flow": 30},
            pd.Timestamp("2026-03-31"): {"Free Cash Flow": 20},
        }
    )
    quarterly_balance_sheet = pd.DataFrame()


class SparseTicker:
    info = {}
    quarterly_financials = pd.DataFrame()
    quarterly_cashflow = pd.DataFrame()
    quarterly_balance_sheet = pd.DataFrame()


class PartialTicker(FullTicker):
    quarterly_cashflow = pd.DataFrame()


class FakeYFinance:
    def __init__(self, ticker=FullTicker):
        self.ticker = ticker

    def Ticker(self, _ticker):
        return self.ticker()


class FixedTechnical:
    def __init__(self, score=80, **indicators):
        self.score = score
        self.indicators = {
            "rsi_14": 60,
            "macd": 2,
            "macd_signal": 1,
            "sma_20": 110,
            "sma_60": 105,
            "sma_120": 100,
            "bb_upper": 140,
            "atr_14": 3,
            **indicators,
        }

    def analyze(self, ticker, _frame):
        return TechnicalAnalysisResult(
            ticker=ticker,
            current_price=120,
            indicators=self.indicators,
            technical_score=self.score,
            score_breakdown={"trend": 30, "momentum": 25, "volume": 15, "volatility": 15},
            trend_label="strong bullish setup",
            data_quality_note="ok",
        )


def asset(**overrides):
    return {
        "id": "asset-1",
        "ticker": "EXM",
        "name": "Example",
        "market": "US",
        "quantity": 10,
        "avg_price": 100,
        "currency": "USD",
        **overrides,
    }


def service(*, technical=None, ticker=FullTicker, current_price=120):
    return ProfitTakingReviewService(
        FakeMarketData(market_data(current_price)),
        FakeYFinance(ticker),
        technical_analysis_service=technical or FixedTechnical(),
        now_provider=lambda: datetime(2026, 7, 31, tzinfo=timezone.utc),
    )


def test_profit_taking_review_selects_sell_only_after_pressure_and_multiple_risks():
    result = service(
        technical=FixedTechnical(
            score=20,
            rsi_14=80,
            macd=-2,
            macd_signal=1,
            sma_20=130,
            sma_60=130,
            bb_upper=115,
        )
    ).analyze(
        asset(),
        "medium",
        portfolio_total_value=3000,
        currency_fx_rate=1,
        max_asset_weight_pct=25,
        upcoming_events=[{"event_type": "earnings", "provider": "yfinance"}],
    )

    assert result["decision"]["action"] == "SELL"
    assert result["scorecard"]["realization_pressure_score"] >= 75
    assert len(result["scorecard"]["risk_categories"]) >= 2


def test_profit_taking_review_reduces_when_position_exceeds_concentration_limit():
    result = service().analyze(
        asset(),
        "medium",
        portfolio_total_value=4000,
        currency_fx_rate=1,
        max_asset_weight_pct=25,
    )

    assert result["decision"]["action"] == "REDUCE"
    assert result["scorecard"]["concentration_exceeded"] is True
    assert "집중도 기준 이상" in result["decision"]["primary_reasons"][0]


def test_profit_taking_review_holds_when_support_is_sufficient_without_add_signal():
    result = service(ticker=type("NoForwardPeTicker", (FullTicker,), {"info": {}})).analyze(
        asset(),
        "medium",
        portfolio_total_value=10000,
        currency_fx_rate=1,
    )

    assert result["decision"]["action"] == "HOLD"
    assert result["scorecard"]["hold_support_score"] >= 60
    assert result["scorecard"]["realization_pressure_score"] < 55


def test_profit_taking_review_buy_is_independent_from_latest_report_buy():
    result = service(technical=FixedTechnical(score=90)).analyze(
        asset(),
        "medium",
        portfolio_total_value=10000,
        currency_fx_rate=1,
        latest_report={"action": "BUY", "confidence": 99, "generated_at": "2026-07-30"},
    )

    assert result["decision"]["action"] == "BUY"
    assert result["report_conflict"]["decision_influence"] == "excluded"
    assert result["decision"]["independent_from_latest_report"] is True
    assert [option["action"] for option in result["option_comparison"]] == [
        "SELL",
        "REDUCE",
        "HOLD",
        "BUY",
    ]
    assert all(
        {"suitability_score", "current_view", "when_it_fits"} <= set(option)
        for option in result["option_comparison"]
    )
    assert result["report_conflict"]["action"] == "BUY"
    assert result["report_conflict"]["confidence"] == 99
    assert result["report_conflict"]["generated_at"] == "2026-07-30"
    assert validate_advisory_result(result)["analysis_type"] == "profit_taking_review"


def test_profit_taking_review_action_does_not_change_with_report_action():
    kwargs = {
        "portfolio_total_value": 10000,
        "currency_fx_rate": 1,
    }
    with_buy_report = service(technical=FixedTechnical(score=90)).analyze(
        asset(),
        "medium",
        latest_report={"action": "BUY", "confidence": 99},
        **kwargs,
    )
    with_sell_report = service(technical=FixedTechnical(score=90)).analyze(
        asset(),
        "medium",
        latest_report={"action": "SELL", "confidence": 20},
        **kwargs,
    )

    assert with_buy_report["decision"] == with_sell_report["decision"]


def test_profit_taking_review_reflects_current_return_in_realization_pressure():
    lower_return = service(current_price=105).analyze(
        asset(),
        "medium",
        portfolio_total_value=10000,
        currency_fx_rate=1,
    )
    higher_return = service(current_price=160).analyze(
        asset(),
        "medium",
        portfolio_total_value=10000,
        currency_fx_rate=1,
    )

    assert lower_return["position_snapshot"]["unrealized_return_pct"] == 5.0
    assert higher_return["position_snapshot"]["unrealized_return_pct"] == 60.0
    assert (
        higher_return["scorecard"]["realization_pressure_score"]
        > lower_return["scorecard"]["realization_pressure_score"]
    )


def test_profit_taking_review_applies_horizon_to_price_and_invalidation_references():
    review_service = service(
        technical=FixedTechnical(
            score=80,
            sma_20=115,
            sma_60=110,
            sma_120=100,
            atr_14=10,
        ),
        current_price=120,
    )
    kwargs = {"portfolio_total_value": 10000, "currency_fx_rate": 1}

    short = review_service.analyze(asset(avg_price=80), "short", **kwargs)
    medium = review_service.analyze(asset(avg_price=80), "medium", **kwargs)
    long = review_service.analyze(asset(avg_price=80), "long", **kwargs)

    assert short["price_framework"]["trend_reference_indicator"] == "sma_20"
    assert medium["price_framework"]["trend_reference_indicator"] == "sma_60"
    assert long["price_framework"]["trend_reference_indicator"] == "sma_120"
    assert short["price_framework"]["profit_protection_reference"] == 110.0
    assert medium["price_framework"]["profit_protection_reference"] == 100.0
    assert long["price_framework"]["profit_protection_reference"] == 90.0
    assert short["invalidation_conditions"][0]["reference_indicator"] == "sma_20"
    assert medium["invalidation_conditions"][0]["reference_indicator"] == "sma_60"
    assert long["invalidation_conditions"][0]["reference_indicator"] == "sma_120"


def test_profit_taking_review_blocks_full_exit_and_add_when_fundamentals_are_missing():
    result = service(
        ticker=SparseTicker,
        technical=FixedTechnical(
            score=20,
            rsi_14=80,
            macd=-2,
            macd_signal=1,
            sma_20=130,
            sma_60=130,
            bb_upper=115,
        ),
    ).analyze(
        asset(),
        "medium",
        portfolio_total_value=3000,
        currency_fx_rate=1,
        upcoming_events=[{"event_type": "earnings", "provider": "yfinance"}],
    )

    assert result["decision"]["action"] == "REDUCE"
    assert result["evaluation_status"] == "partial"
    assert result["scorecard"]["data_limited_actions_blocked"] == ["SELL", "BUY"]


def test_profit_taking_review_blocks_strong_actions_for_partial_fundamentals():
    result = service(ticker=PartialTicker, technical=FixedTechnical(score=90)).analyze(
        asset(),
        "medium",
        portfolio_total_value=10000,
        currency_fx_rate=1,
    )

    assert result["scorecard"]["fundamentals_status"] == "partial"
    assert result["decision"]["action"] not in {"SELL", "BUY"}
    assert result["evaluation_status"] == "partial"


def test_profit_taking_review_blocks_strong_actions_when_concentration_is_unknown():
    result = service(technical=FixedTechnical(score=90)).analyze(
        asset(),
        "medium",
        portfolio_total_value=None,
        currency_fx_rate=1,
    )

    assert result["scorecard"]["concentration_available"] is False
    assert result["decision"]["action"] not in {"SELL", "BUY"}
    assert result["evaluation_status"] == "partial"


def test_profit_taking_review_does_not_assume_one_to_one_fx_when_usd_rate_is_missing():
    result = service(technical=FixedTechnical(score=90)).analyze(
        asset(currency="KRW"),
        "medium",
        portfolio_total_value=10000000,
        currency_fx_rate=None,
    )

    assert result["position_snapshot"]["position_weight_pct"] is None
    assert result["scorecard"]["concentration_available"] is False
    assert result["decision"]["action"] not in {"SELL", "BUY"}


def test_profit_taking_review_fails_closed_for_loss_or_zero_return_position():
    result = service(current_price=100).analyze(asset(), "medium")

    assert result["decision"]["action"] == "WATCH"
    assert result["evaluation_status"] == "not_applicable"
    assert result["decision"]["confidence"] == 0
