"""Normalize generated report content against backend-owned facts."""

from collections.abc import Mapping
from typing import Any, TypedDict

from app.models.report import AssetStrategy, ReportContent
from app.services.report.prompt_builder import DISCLAIMER
from app.utils.tickers import normalize_ticker


class FactCorrection(TypedDict, total=False):
    """A safe audit record that never includes generated or backend values."""

    ticker: str
    fields: list[str]


BACKEND_STRATEGY_FIELDS = (
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
)
FORBIDDEN_NARRATIVE_TERMS = (
    "guaranteed profit",
    "certain return",
    "risk-free",
    "must buy",
    "must sell",
    "수익 보장",
    "확실한 수익",
    "무위험",
    "반드시 매수",
    "반드시 매도",
)


def enforce_report_facts(
    content: ReportContent,
    analysis_rows: list[dict[str, Any]],
    portfolio_summary: dict[str, Any],
    index_rows: Mapping[str, Any],
    report_type: str,
    generated_at: str,
) -> tuple[ReportContent, list[FactCorrection]]:
    """Return a report with backend-owned facts restored and a safe correction audit.

    Generated prose remains useful for fresh data, but every quantitative strategy field,
    report timestamp/type, portfolio totals, index rows, and disclaimer come from backend
    inputs. The function has no I/O and never mutates any supplied object.
    """
    corrections: list[FactCorrection] = []
    backend_rows = _backend_rows_by_ticker(analysis_rows, corrections)
    ai_strategies = _recognized_ai_strategies(
        content.asset_strategies,
        backend_rows,
        corrections,
    )

    enforced_strategies = []
    for ticker, row in backend_rows.items():
        backend_strategy = row["strategy"]
        ai_strategy = ai_strategies.get(ticker)
        is_data_limited = _is_data_limited(row, backend_strategy)

        if ai_strategy is None:
            enforced_strategies.append(backend_strategy)
            _add_correction(corrections, backend_strategy.ticker, ["asset_strategies"])
            continue

        if is_data_limited:
            enforced_strategies.append(backend_strategy)
            _add_correction(
                corrections,
                backend_strategy.ticker,
                _changed_fields(ai_strategy, backend_strategy, AssetStrategy.model_fields),
            )
            continue

        enforced_strategies.append(
            backend_strategy.model_copy(
                update={
                    "reasoning": ai_strategy.reasoning,
                    "risk": ai_strategy.risk,
                    "invalidation_condition": ai_strategy.invalidation_condition,
                }
            )
        )
        _add_correction(
            corrections,
            backend_strategy.ticker,
            _changed_fields(ai_strategy, backend_strategy, BACKEND_STRATEGY_FIELDS),
        )

    portfolio = content.portfolio_summary.model_copy(
        update={
            "total_market_value": portfolio_summary["total_market_value"],
            "total_return_rate": portfolio_summary["total_return_rate"],
            "risk_level": portfolio_summary.get(
                "risk_level",
                content.portfolio_summary.risk_level,
            ),
        }
    )
    portfolio_fields = _changed_mapping_fields(
        content.portfolio_summary,
        portfolio,
        ("total_market_value", "total_return_rate", "risk_level"),
    )
    _add_correction(corrections, None, portfolio_fields)

    key_indices = [_index_payload(name, result) for name, result in index_rows.items()]
    market_summary = content.market_summary.model_copy(update={"key_indices": key_indices})
    market_fields = (
        ["market_summary.key_indices"] if content.market_summary.key_indices != key_indices else []
    )
    _add_correction(corrections, None, market_fields)

    report_fields = []
    if content.report_type != report_type:
        report_fields.append("report_type")
    if content.generated_at != generated_at:
        report_fields.append("generated_at")
    if content.disclaimer != DISCLAIMER:
        report_fields.append("disclaimer")
    _add_correction(corrections, None, report_fields)

    return (
        content.model_copy(
            update={
                "report_type": report_type,
                "generated_at": generated_at,
                "market_summary": market_summary,
                "portfolio_summary": portfolio,
                "asset_strategies": enforced_strategies,
                "disclaimer": DISCLAIMER,
            }
        ),
        corrections,
    )


def forbidden_narrative_paths(content: ReportContent) -> list[str]:
    fields: list[tuple[str, str]] = [
        ("market_summary.summary", content.market_summary.summary),
        ("portfolio_summary.allocation_comment", content.portfolio_summary.allocation_comment),
        *[
            (f"market_summary.macro_factors[{index}]", value)
            for index, value in enumerate(content.market_summary.macro_factors)
        ],
        *[(f"key_risks[{index}]", value) for index, value in enumerate(content.key_risks)],
        *[(f"opportunities[{index}]", value) for index, value in enumerate(content.opportunities)],
    ]
    for index, strategy in enumerate(content.asset_strategies):
        fields.extend(
            [
                (f"asset_strategies[{index}].reasoning", strategy.reasoning),
                (f"asset_strategies[{index}].risk", strategy.risk),
                (
                    f"asset_strategies[{index}].invalidation_condition",
                    strategy.invalidation_condition,
                ),
            ]
        )
    return [
        path
        for path, value in fields
        if any(term in value.casefold() for term in FORBIDDEN_NARRATIVE_TERMS)
    ]


def _backend_rows_by_ticker(
    analysis_rows: list[dict[str, Any]],
    corrections: list[FactCorrection],
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in analysis_rows:
        strategy = row["strategy"]
        ticker = normalize_ticker(row["asset"].get("ticker", strategy.ticker))
        if ticker in rows:
            _add_correction(corrections, strategy.ticker, ["asset_strategies"])
            continue
        rows[ticker] = row
    return rows


def _recognized_ai_strategies(
    strategies: list[AssetStrategy],
    backend_rows: Mapping[str, dict[str, Any]],
    corrections: list[FactCorrection],
) -> dict[str, AssetStrategy]:
    recognized: dict[str, AssetStrategy] = {}
    for strategy in strategies:
        ticker = normalize_ticker(strategy.ticker)
        row = backend_rows.get(ticker)
        if row is None:
            _add_correction(corrections, None, ["asset_strategies"])
            continue
        if ticker in recognized:
            _add_correction(corrections, row["strategy"].ticker, ["asset_strategies"])
            continue
        recognized[ticker] = strategy
    return recognized


def _is_data_limited(row: Mapping[str, Any], strategy: AssetStrategy) -> bool:
    market_data = row.get("market_data")
    return bool(_value(market_data, "is_stale", False)) or strategy.reasoning == "data-limited"


def _index_payload(name: str, result: Any) -> dict[str, Any]:
    return {
        "name": name,
        "technical_score": _value(result, "technical_score"),
        "trend_label": _value(result, "trend_label"),
    }


def _value(source: Any, field: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(field, default)
    return getattr(source, field, default)


def _changed_fields(
    source: AssetStrategy,
    corrected: AssetStrategy,
    fields: Any,
) -> list[str]:
    return [field for field in fields if getattr(source, field) != getattr(corrected, field)]


def _changed_mapping_fields(source: Any, corrected: Any, fields: tuple[str, ...]) -> list[str]:
    return [field for field in fields if getattr(source, field) != getattr(corrected, field)]


def _add_correction(
    corrections: list[FactCorrection],
    ticker: str | None,
    fields: list[str],
) -> None:
    if not fields:
        return
    entry: FactCorrection = {"fields": fields}
    if ticker:
        entry["ticker"] = ticker
    corrections.append(entry)
