"""Normalize generated report content against backend-owned facts."""

from collections.abc import Mapping
import re
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

# The model tags a news-backed sentence with [[N1]] so attribution stays measurable;
# the marker is removed here, before the report is stored or shown.
_EVIDENCE_MARKER_PATTERN = re.compile(r"\s*\[\[[^\[\]]{1,64}\]\]")
# A bracketed aside is only removed when it holds a URL or opens with an evidence id
# (N1/E12), never merely because it contains a letter that appears in "evidence".
_BRACKETED_SOURCE_PATTERN = re.compile(r"\[(?:[^\]]*https?://[^\]]*|\s*[NE]\d+\b[^\]]*)\]")
_URL_PATTERN = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_NEWS_PROVIDER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])GDELT(?:\s+DOC\s+2\.0)?(?![A-Za-z0-9])", re.IGNORECASE
)
_DANGLING_SOURCE_LABEL_PATTERN = re.compile(
    r"(?:출처|source)\s*[:：]\s*(?=[,.;)\]]|$)", re.IGNORECASE
)
_SPACE_BEFORE_PUNCTUATION_PATTERN = re.compile(r"\s+([,.;:!?])")
_EMPTY_PARENTHESES_PATTERN = re.compile(r"\(\s*\)|\[\s*\]|（\s*）")


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


def redact_source_references(
    content: ReportContent,
    articles: list[dict[str, Any]] | None = None,
) -> tuple[ReportContent, list[str]]:
    """Strip evidence markers and news-source identifiers from user-facing narrative text.

    The prompt forbids them, but a prompt rule has no failure signal. Running the
    redaction here — before persistence — means the stored report, the API payload,
    and every consumer (exports, notifications, any future client) see the same clean
    text, instead of relying on one display component to opt in.
    """
    patterns = _source_patterns(articles or [])
    redacted: list[str] = []

    def clean(path: str, value: str) -> str:
        result = _redact(value, patterns)
        if result != value:
            redacted.append(path)
        return result

    def clean_list(prefix: str, values: list[str]) -> list[str]:
        cleaned = (clean(f"{prefix}[{index}]", value) for index, value in enumerate(values))
        # A bullet that was nothing but a citation must disappear, not render blank.
        return [value for value in cleaned if value]

    market_summary = content.market_summary.model_copy(
        update={
            "summary": clean("market_summary.summary", content.market_summary.summary),
            "macro_factors": clean_list(
                "market_summary.macro_factors", list(content.market_summary.macro_factors)
            ),
        }
    )
    portfolio_summary = content.portfolio_summary.model_copy(
        update={
            "allocation_comment": clean(
                "portfolio_summary.allocation_comment",
                content.portfolio_summary.allocation_comment,
            )
        }
    )
    strategies = [
        strategy.model_copy(
            update={
                "reasoning": clean(f"asset_strategies[{index}].reasoning", strategy.reasoning),
                "risk": clean(f"asset_strategies[{index}].risk", strategy.risk),
                "invalidation_condition": clean(
                    f"asset_strategies[{index}].invalidation_condition",
                    strategy.invalidation_condition,
                ),
            }
        )
        for index, strategy in enumerate(content.asset_strategies)
    ]
    return (
        content.model_copy(
            update={
                "market_summary": market_summary,
                "portfolio_summary": portfolio_summary,
                "key_risks": clean_list("key_risks", list(content.key_risks)),
                "opportunities": clean_list("opportunities", list(content.opportunities)),
                "asset_strategies": strategies,
            }
        ),
        redacted,
    )


def _source_patterns(articles: list[dict[str, Any]]) -> list[re.Pattern[str]]:
    """Match the exact domains and publisher names the report was actually fed.

    Deriving the terms from the fetched articles keeps this precise: a generic
    "looks like a hostname" rule cannot tell reuters.com from the 005930.KS ticker
    suffix that legitimately appears in Korean report prose.
    """
    terms: set[str] = set()
    for article in articles:
        domain = str(article.get("domain") or "").strip().lower()
        if not domain:
            continue
        terms.add(domain)
        labels = [label for label in domain.split(".") if label and label != "www"]
        if len(labels) >= 2:
            # "reuters.com" also blocks a bare "Reuters" mention.
            terms.add(labels[-2])
    # ASCII-only boundaries, because \b does not fire between "Reuters" and a
    # following Hangul syllable: Python treats both sides as word characters.
    return [
        re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)
        for term in sorted(terms, key=len, reverse=True)
        if len(term) >= 3
    ]


def _redact(value: str, patterns: list[re.Pattern[str]]) -> str:
    if not value:
        return value
    result = _EVIDENCE_MARKER_PATTERN.sub("", value)
    result = _BRACKETED_SOURCE_PATTERN.sub("", result)
    result = _URL_PATTERN.sub("", result)
    result = _NEWS_PROVIDER_PATTERN.sub("", result)
    for pattern in patterns:
        result = pattern.sub("", result)
    result = _DANGLING_SOURCE_LABEL_PATTERN.sub("", result)
    result = _SPACE_BEFORE_PUNCTUATION_PATTERN.sub(r"\1", result)
    result = _EMPTY_PARENTHESES_PATTERN.sub("", result)
    return " ".join(result.split()).strip(" ·,")


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
