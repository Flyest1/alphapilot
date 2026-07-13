from types import SimpleNamespace

from app.models.report import AssetStrategy, MarketSummary, PortfolioSummary, ReportContent
from app.services.report.fact_enforcer import enforce_report_facts, forbidden_narrative_paths
from app.services.report.prompt_builder import DISCLAIMER


def strategy(ticker: str, *, reasoning: str = "backend reasoning", **overrides) -> AssetStrategy:
    values = {
        "ticker": ticker,
        "name": f"Backend {ticker}",
        "current_price": 100.0,
        "action": "BUY",
        "confidence": 71,
        "buy_range_low": 95.0,
        "buy_range_high": 102.0,
        "sell_range_low": None,
        "sell_range_high": None,
        "target_price": 115.0,
        "stop_loss": 90.0,
        "reasoning": reasoning,
        "risk": "backend risk",
        "invalidation_condition": "backend invalidation",
        "confidence_detail": {"technical_confidence": 71},
        "position_sizing": {"amount_low": 10000, "amount_high": 20000},
    }
    values.update(overrides)
    return AssetStrategy(**values)


def report_content(*strategies: AssetStrategy) -> ReportContent:
    return ReportContent(
        report_type="global",
        generated_at="ai-time",
        market_summary=MarketSummary(
            summary="AI market summary",
            key_indices=[{"name": "AI", "technical_score": 1}],
            macro_factors=["AI macro factor"],
        ),
        portfolio_summary=PortfolioSummary(
            total_market_value=1.0,
            total_return_rate=-99.0,
            risk_level="high",
            allocation_comment="AI allocation comment",
        ),
        key_risks=["AI key risk"],
        opportunities=["AI opportunity"],
        asset_strategies=list(strategies),
        disclaimer="AI disclaimer",
    )


def analysis_row(
    backend_strategy: AssetStrategy,
    *,
    asset_ticker: str | None = None,
    is_stale: bool = False,
) -> dict:
    return {
        "asset": {"ticker": asset_ticker or backend_strategy.ticker},
        "strategy": backend_strategy,
        "market_data": SimpleNamespace(is_stale=is_stale),
    }


def test_enforcer_restores_backend_facts_and_preserves_fresh_ai_narrative():
    backend = strategy("AAPL")
    ai = strategy(
        "AAPL",
        name="AI Apple",
        current_price=1.0,
        action="SELL",
        confidence=3,
        buy_range_low=1.0,
        buy_range_high=2.0,
        target_price=4.0,
        stop_loss=0.5,
        reasoning="AI reasoning",
        risk="AI risk",
        invalidation_condition="AI invalidation",
        confidence_detail={"technical_confidence": 3},
        position_sizing={"amount_low": 1},
    )
    content = report_content(ai)

    corrected, corrections = enforce_report_facts(
        content,
        [analysis_row(backend)],
        {"total_market_value": 500000.0, "total_return_rate": 12.5, "risk_level": "low"},
        {"S&P 500": SimpleNamespace(technical_score=88, trend_label="strong bullish setup")},
        "domestic",
        "2026-07-12T08:30:00+09:00",
    )

    enforced = corrected.asset_strategies[0]
    for field in (
        "ticker",
        "name",
        "current_price",
        "action",
        "confidence",
        "buy_range_low",
        "buy_range_high",
        "sell_range_low",
        "sell_range_high",
        "target_price",
        "stop_loss",
        "confidence_detail",
        "position_sizing",
    ):
        assert getattr(enforced, field) == getattr(backend, field)
    assert enforced.reasoning == "AI reasoning"
    assert enforced.risk == "AI risk"
    assert enforced.invalidation_condition == "AI invalidation"
    assert corrected.report_type == "domestic"
    assert corrected.generated_at == "2026-07-12T08:30:00+09:00"
    assert corrected.portfolio_summary.total_market_value == 500000.0
    assert corrected.portfolio_summary.total_return_rate == 12.5
    assert corrected.portfolio_summary.risk_level == "low"
    assert corrected.portfolio_summary.allocation_comment == "AI allocation comment"
    assert corrected.market_summary.summary == "AI market summary"
    assert corrected.market_summary.macro_factors == ["AI macro factor"]
    assert corrected.market_summary.key_indices == [
        {"name": "S&P 500", "technical_score": 88, "trend_label": "strong bullish setup"}
    ]
    assert corrected.disclaimer == DISCLAIMER
    assert any(item.get("ticker") == "AAPL" for item in corrections)


def test_enforcer_removes_unknown_and_normalized_duplicates_in_backend_order_without_values():
    samsung = strategy("005930")
    apple = strategy("AAPL")
    duplicate = strategy("005930", reasoning="duplicate narrative")
    normalized = strategy("005930.KS", reasoning="normalized narrative")
    unknown = strategy("MALLORY", reasoning="do not expose")

    corrected, corrections = enforce_report_facts(
        report_content(apple, normalized, duplicate, unknown),
        [analysis_row(samsung), analysis_row(apple)],
        {"total_market_value": 0.0, "total_return_rate": 0.0},
        {},
        "domestic",
        "2026-07-12T08:30:00+09:00",
    )

    assert [item.ticker for item in corrected.asset_strategies] == ["005930", "AAPL"]
    assert corrected.asset_strategies[0].reasoning == "normalized narrative"
    assert corrected.asset_strategies[1] == apple
    assert all(set(item).issubset({"ticker", "fields"}) for item in corrections)
    assert all(
        set(item["fields"]).issubset(
            {
                "asset_strategies",
                "report_type",
                "generated_at",
                "disclaimer",
                "total_market_value",
                "total_return_rate",
                "risk_level",
                "market_summary.key_indices",
                "ticker",
                "name",
                "current_price",
                "action",
                "confidence",
                "buy_range_low",
                "buy_range_high",
                "sell_range_low",
                "sell_range_high",
                "target_price",
                "stop_loss",
                "reasoning",
                "risk",
                "invalidation_condition",
                "confidence_detail",
                "position_sizing",
            }
        )
        for item in corrections
    )
    assert "MALLORY" not in str(corrections)
    assert "do not expose" not in str(corrections)


def test_enforcer_uses_backend_strategy_for_stale_or_data_limited_rows_without_mutation():
    stale_backend = strategy("MSFT", reasoning="data-limited", confidence=0, action="WATCH")
    data_limited_backend = strategy("NVDA", reasoning="data-limited", confidence=0, action="WATCH")
    stale_ai = strategy(
        "MSFT", reasoning="AI stale reasoning", risk="AI stale risk", confidence=99, action="BUY"
    )
    data_limited_ai = strategy(
        "NVDA",
        reasoning="AI unavailable reasoning",
        risk="AI unavailable risk",
        confidence=99,
        action="BUY",
    )
    content = report_content(stale_ai, data_limited_ai)
    original = content.model_dump()

    corrected, corrections = enforce_report_facts(
        content,
        [
            analysis_row(stale_backend, is_stale=True),
            analysis_row(data_limited_backend),
        ],
        {"total_market_value": 10.0, "total_return_rate": 1.0},
        {},
        "global",
        "2026-07-12T22:30:00+09:00",
    )

    assert corrected.asset_strategies == [stale_backend, data_limited_backend]
    assert content.model_dump() == original
    assert {item["ticker"] for item in corrections if "ticker" in item} == {"MSFT", "NVDA"}


def test_forbidden_narrative_paths_report_safe_paths_only():
    content = report_content(strategy("AAPL", reasoning="반드시 매수하면 수익 보장"))

    assert forbidden_narrative_paths(content) == ["asset_strategies[0].reasoning"]
