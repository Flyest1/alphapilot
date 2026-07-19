"""LLM 리포트 프롬프트와 컨텍스트 조립 모듈."""

from typing import Any

from app.models.report import AssetStrategy
from app.services.technical_analysis_service import TechnicalAnalysisResult

DISCLAIMER = "이 리포트는 투자 의사결정 지원용이며 자동 매매를 실행하지 않습니다."
PROMPT_VERSION = "2026-07-r4"


def build_prompt(report_type: str) -> str:
    return (
        f"Generate a {report_type} AlphaPilot report as JSON matching ReportContent exactly. "
        "The root object must contain only report_type, generated_at, market_summary, "
        "portfolio_summary, key_risks, opportunities, asset_strategies, and disclaimer. "
        "Use context.generated_at as generated_at. market_summary must be an object with "
        "summary, key_indices, and macro_factors. portfolio_summary must be an object with "
        "total_market_value, total_return_rate, risk_level, and allocation_comment only. "
        "asset_strategies must use the technical_strategies input shape and must not be named "
        "strategies. Do not add market_view, portfolio_notes, stale_tickers, risk_profile, "
        "total_cost, total_profit_loss, domestic_value, global_value, or cash_value to the "
        "output. Use decision-support language only. Do not add a news_factors field. Include "
        "action, confidence, ranges, target, stop-loss, reasoning, risk, and invalidation "
        "condition for each non-stale strategy. Write user-facing text fields in Korean, "
        "Copy every quantitative and enum value from context exactly. Backend-owned fields are "
        "report_type, generated_at, market_summary.key_indices, portfolio numeric values, and "
        "each strategy's ticker, name, current_price, action, confidence, ranges, target_price, "
        "stop_loss, confidence_detail, and position_sizing. Only author narrative text in summary, "
        "macro_factors, key_risks, opportunities, allocation_comment, reasoning, risk, and "
        "invalidation_condition. Never add a ticker absent from context.technical_strategies. "
        "including market_summary.summary, macro_factors, key_risks, opportunities, "
        "reasoning, risk, invalidation_condition, and allocation_comment. Keep schema keys, "
        "ticker symbols, and action enum values in English exactly as required. Do not write "
        "English sentences in user-facing fields unless the field value is a ticker, provider "
        "name, schema key, or action enum. context.candidate_tickers contains non-owned "
        "screened buy candidates. Include them in asset_strategies when they are present, and "
        "make their reasoning clearly say they are 보유 외 추가 매수 후보. "
        "For non-owned candidates, do not use HOLD; use BUY for active entry ideas and WATCH "
        "for waitlisted ideas. "
        "context.candidate_horizon is the target holding/profit-taking horizon for those "
        "candidate ideas. context.news_context contains recent headline-only news/trend inputs. "
        "Use them only as limited internal context; do not imply that article body text was read. "
        "Never expose evidence IDs, URLs, domains, publisher or site names, news providers, or "
        "GDELT in user-facing text. If news_context has no articles, assign no news contribution "
        "and state the evidence limitation when relevant. "
        "context.advisory_context contains bounded summaries of recent completed manual advisory "
        "analyses. Treat them as historical decision-support inputs, not fresh market facts or "
        "trade instructions. Use an advisory only when it is directly relevant to the current "
        "report type or a ticker in context.technical_strategies. Never let advisory context "
        "override fresh prices, technical strategies, actions, confidence, targets, or stop-loss "
        "values. Do not transfer US or ETF security-level conclusions to unrelated domestic "
        "assets. Use advisory data-quality limitations, and never expose analysis IDs, request "
        "data, evidence identifiers, URLs, or provider credentials. "
        "context.asset_events contains upcoming owned-asset earnings/dividend dates from "
        "yfinance. Surface relevant event risk/opportunity only in existing allowed fields. "
        "Use it only when relevant inside allowed fields such as macro_factors, key_risks, "
        "opportunities, reasoning, and risk. Do not cite unsupported details or create a "
        "separate news section."
    )


def build_context(
    report_type: str,
    app_settings: dict[str, Any],
    portfolio_summary: dict[str, Any],
    analysis_rows: list[dict[str, Any]],
    index_rows: dict[str, TechnicalAnalysisResult],
    technical_strategies: list[AssetStrategy],
    owned_tickers: list[str],
    stale_tickers: list[str],
    news_context: dict[str, Any],
    asset_events: dict[str, Any],
    advisory_context: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    return {
        "report_type": report_type,
        "settings": app_settings,
        "portfolio_summary": portfolio_summary,
        "market_indices": {key: value.__dict__ for key, value in index_rows.items()},
        "technical_strategies": [
            strategy.model_dump(mode="json") for strategy in technical_strategies
        ],
        "owned_tickers": owned_tickers,
        "candidate_tickers": [
            row["asset"]["ticker"] for row in analysis_rows if row["asset"].get("id") is None
        ],
        "candidate_horizon": app_settings.get("candidate_horizon", "medium"),
        "stale_tickers": stale_tickers,
        "news_context": news_context,
        "asset_events": asset_events,
        "advisory_context": advisory_context,
        "generated_at": generated_at,
        "asset_context": [
            {
                "asset": row["asset"],
                "market_data": {
                    "provider": row["market_data"].provider,
                    "last_trading_date": row["market_data"].last_trading_date,
                    "is_stale": row["market_data"].is_stale,
                    "data_quality_note": row["market_data"].data_quality_note,
                },
                "technical_analysis": row["technical_analysis"].__dict__,
            }
            for row in analysis_rows
            if not row["market_data"].is_stale and row["strategy"].reasoning != "data-limited"
        ],
        "disclaimer": DISCLAIMER,
    }
