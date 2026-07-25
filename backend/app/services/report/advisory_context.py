"""Bounded, non-sensitive advisory context for report generation."""

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
import json
from typing import Any

from app.db.supabase_client import Repository
from app.utils.datetime import parse_iso_datetime
from app.utils.logging import log_external_failure

ADVISORY_LOOKBACK_DAYS = 30
MAX_ADVISORY_ANALYSES = 8
MAX_ADVISORY_CONTEXT_BYTES = 12_000
MAX_ADVISORY_TICKERS = 5
MAX_ADVISORY_ACTIONS = 5
MAX_ADVISORY_ITEMS = 3

# Each advisory type maps to the result-payload key holding its per-row findings.
# Keep this aligned with the result models in app/models/advisory.py.
_FINDING_COLLECTIONS = {
    "undervalued_us_stocks": "top_candidates",
    "etf_rebalancing": "etfs",
    "post_earnings_opportunities": "rankings",
    "ai_beneficiaries": "verified_ai_beneficiaries",
    "high_dividend_etfs": "etfs",
    "etf_overlap": "etfs",
    "sector_outlook": "sectors",
    "sec_filing_risk": "risk_categories",
}
_ADVISORY_TYPES = frozenset(_FINDING_COLLECTIONS)
# One ordered query is enough to find the newest row per type; fetching a bounded
# page keeps report generation to a single round trip instead of one call per type.
ADVISORY_FETCH_LIMIT = len(_FINDING_COLLECTIONS) * MAX_ADVISORY_ANALYSES
_SAFE_ACTIONS = {"BUY", "HOLD", "REDUCE", "SELL", "WATCH"}
_SAFE_ITEM_FIELDS = {
    "ticker",
    "sector",
    "action",
    "category",
    "status",
    "classification",
    "analysis_status",
    "data_quality_status",
    "investment_appeal_10",
    "investment_score",
    "opportunity_score",
    "stability_score",
    "overheating_risk_10",
    "long_term_growth_10",
    "attractiveness_score",
    "attractiveness_label",
    "risk_rating",
    "current_weight_pct",
    "portfolio_exposure_pct",
    "top10_overlap_pct",
    "minimum_confirmed_overlap_pct",
    "minimum_confirmed_top10_overlap_pct",
}


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# Constant overhead of the returned envelope, so the byte budget can be tracked
# incrementally instead of re-serializing every accepted summary on each iteration.
_ENVELOPE_BYTES = len(
    _dumps(
        {
            "status": "available",
            "lookback_days": ADVISORY_LOOKBACK_DAYS,
            "analysis_count": MAX_ADVISORY_ANALYSES,
            "truncated": True,
            "analyses": [],
        }
    ).encode("utf-8")
)


def build_advisory_context(
    repository: Repository,
    *,
    now_provider: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Return recent completed advisory summaries without raw requests or narratives."""
    now = now_provider() if now_provider else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now.astimezone(timezone.utc) - timedelta(days=ADVISORY_LOOKBACK_DAYS)

    # Every step that touches repository output stays inside the guard: report
    # generation must survive an unreadable or malformed advisory store.
    try:
        fetched = repository.list_advisory_analyses(limit=ADVISORY_FETCH_LIMIT) or []
        rows = _recent_rows(fetched, cutoff)
    except Exception as exc:
        log_external_failure(
            "advisory_analyses",
            exc,
            {"operation": "build_report_advisory_context"},
        )
        return {
            "status": "unavailable",
            "lookback_days": ADVISORY_LOOKBACK_DAYS,
            "analysis_count": 0,
            "truncated": False,
            "analyses": [],
        }

    analyses: list[dict[str, Any]] = []
    analysis_types: set[str] = set()
    # A full page means older rows were never fetched, so the newest run of a
    # rarely-used type may be missing from this context.
    truncated = len(fetched) >= ADVISORY_FETCH_LIMIT
    size = _ENVELOPE_BYTES
    for row in rows:
        if len(analyses) >= MAX_ADVISORY_ANALYSES:
            truncated = True
            break
        try:
            summary = _summarize_analysis(row)
        except Exception as exc:
            log_external_failure(
                "advisory_analyses",
                exc,
                {"operation": "summarize_report_advisory_context"},
            )
            continue
        if summary is None or summary["analysis_type"] in analysis_types:
            continue
        # +1 covers the comma separating this summary from the previous one.
        summary_bytes = len(_dumps(summary).encode("utf-8")) + 1
        if size + summary_bytes > MAX_ADVISORY_CONTEXT_BYTES:
            truncated = True
            break
        size += summary_bytes
        analyses.append(summary)
        analysis_types.add(summary["analysis_type"])
    return {
        "status": "available",
        "lookback_days": ADVISORY_LOOKBACK_DAYS,
        "analysis_count": len(analyses),
        "truncated": truncated,
        "analyses": analyses,
    }


def _recent_rows(fetched: Any, cutoff: datetime) -> list[Mapping[str, Any]]:
    """Return in-window advisory rows, newest first, skipping anything unusable."""
    dated: list[tuple[datetime, Mapping[str, Any]]] = []
    for row in fetched if isinstance(fetched, list) else []:
        if not isinstance(row, Mapping):
            continue
        if row.get("analysis_type") not in _ADVISORY_TYPES:
            continue
        created_at = _parse_timestamp(row.get("created_at"))
        if created_at is None or created_at < cutoff:
            continue
        dated.append((created_at, row))
    # Sort on the parsed instant: ISO strings with differing offsets do not sort
    # lexicographically in chronological order.
    dated.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in dated]


def _summarize_analysis(row: Mapping[str, Any]) -> dict[str, Any] | None:
    result = row.get("result_payload")
    analysis_type = _safe_identifier(row.get("analysis_type"))
    if not analysis_type or not isinstance(result, Mapping):
        return None

    data_quality = result.get("data_quality")
    evidence = result.get("evidence")
    return {
        "analysis_id": _safe_identifier(row.get("analysis_id")),
        "analysis_type": analysis_type,
        "created_at": _safe_timestamp(row.get("created_at")),
        "generated_at": _safe_timestamp(result.get("generated_at")),
        "retrieved_at": _safe_timestamp(result.get("retrieved_at")),
        "data_quality": {
            "status": _safe_identifier(
                data_quality.get("status") if isinstance(data_quality, Mapping) else None
            ),
            "limitations": _safe_notes(
                data_quality.get("limitations") if isinstance(data_quality, Mapping) else None
            ),
            "limitation_count": _length(
                data_quality.get("limitations") if isinstance(data_quality, Mapping) else None
            ),
            "missing_field_count": _length(
                data_quality.get("missing_fields") if isinstance(data_quality, Mapping) else None
            ),
        },
        # Provider names are deliberately omitted: they are vendor identifiers the
        # report must never surface, and the advisory evidence list mixes in the
        # news provider (see AdvisoryPipeline._attach_news_context).
        "evidence": {"count": _length(evidence)},
        "findings": _findings(analysis_type, result),
    }


def _findings(analysis_type: str, result: Mapping[str, Any]) -> dict[str, Any]:
    collection = result.get(_FINDING_COLLECTIONS.get(analysis_type, ""))
    items = collection if isinstance(collection, list) else []
    tickers = _collect_tickers(items)
    actions = _collect_actions(items)
    findings: dict[str, Any] = {
        "result_count": len(items),
        "tickers": tickers,
        "actions": actions,
    }
    top_items = _summarize_items(items)
    if top_items:
        findings["top_items"] = top_items
    if analysis_type == "sec_filing_risk":
        ticker = _safe_identifier(result.get("ticker"))
        if ticker:
            findings["tickers"] = [ticker]
        findings["risk_rating"] = _safe_identifier(result.get("risk_rating"))
        findings["evaluation_status"] = _safe_identifier(result.get("evaluation_status"))
    return findings


def _collect_tickers(items: list[Any]) -> list[str]:
    tickers = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        ticker = _safe_identifier(item.get("ticker"))
        if ticker and ticker not in tickers:
            tickers.append(ticker)
        if len(tickers) >= MAX_ADVISORY_TICKERS:
            break
    return tickers


def _collect_actions(items: list[Any]) -> list[str]:
    actions = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        action = _safe_identifier(item.get("action"))
        if action in _SAFE_ACTIONS and action not in actions:
            actions.append(action)
        if len(actions) >= len(_SAFE_ACTIONS):
            break
    return actions


def _summarize_items(items: list[Any]) -> list[dict[str, Any]]:
    summaries = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        summary = {
            key: safe_value
            for key, value in item.items()
            if key in _SAFE_ITEM_FIELDS and (safe_value := _safe_scalar(value)) is not None
        }
        if summary:
            summaries.append(summary)
        if len(summaries) >= MAX_ADVISORY_ITEMS:
            break
    return summaries


def _length(value: Any) -> int:
    """Report the real length: these are counts, not payloads that need bounding."""
    return len(value) if isinstance(value, list) else 0


def _safe_notes(value: Any) -> list[str]:
    """Keep the data-quality limitation text the prompt asks the model to weigh."""
    if not isinstance(value, list):
        return []
    notes = []
    for item in value:
        if not isinstance(item, str):
            continue
        note = " ".join(item.split())[:160]
        if note:
            notes.append(note)
        if len(notes) >= MAX_ADVISORY_ITEMS:
            break
    return notes


def _safe_identifier(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    compact = "".join(
        character
        for character in value
        if character.isascii() and (character.isalnum() or character in "._:- ")
    )
    return " ".join(compact.split())[:80] or None


def _safe_timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value[:64] or None


def _safe_scalar(value: Any) -> str | int | float | bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if abs(value) <= 1_000_000_000_000 else None
    return _safe_identifier(value)


def _parse_timestamp(value: Any) -> datetime | None:
    parsed = parse_iso_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
