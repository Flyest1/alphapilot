"""Bounded, non-sensitive advisory context for report generation."""

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
import json
from typing import Any

from app.db.supabase_client import Repository
from app.utils.logging import log_external_failure

ADVISORY_LOOKBACK_DAYS = 30
MAX_ADVISORY_ANALYSES = 9
MAX_ADVISORY_CONTEXT_BYTES = 12_000
MAX_ADVISORY_TICKERS = 5
MAX_ADVISORY_ACTIONS = 5
MAX_ADVISORY_PROVIDERS = 3
MAX_ADVISORY_ITEMS = 3

_FINDING_COLLECTIONS = {
    "undervalued_us_stocks": "top_candidates",
    "etf_rebalancing": "etfs",
    "post_earnings_opportunities": "rankings",
    "ai_beneficiaries": "verified_ai_beneficiaries",
    "high_dividend_etfs": "etfs",
    "etf_overlap": "etfs",
    "sector_outlook": "sectors",
}
_ADVISORY_TYPES = (*_FINDING_COLLECTIONS, "sec_filing_risk", "profit_taking_review")
_SAFE_ACTIONS = {"BUY", "HOLD", "REDUCE", "SELL", "WATCH"}
_SAFE_ITEM_FIELDS = {
    "ticker",
    "sector",
    "action",
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
    "overlap_pct",
    "company_weight_pct",
}


def build_advisory_context(
    repository: Repository,
    *,
    now_provider: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    """Return recent completed advisory summaries without raw requests or narratives."""
    try:
        rows = [
            row
            for analysis_type in _ADVISORY_TYPES
            for row in repository.list_advisory_analyses(
                analysis_type=analysis_type,
                limit=1,
            )
        ]
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
            "analyses": [],
        }

    now = now_provider() if now_provider else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    cutoff = now.astimezone(timezone.utc) - timedelta(days=ADVISORY_LOOKBACK_DAYS)
    analyses: list[dict[str, Any]] = []
    analysis_types: set[str] = set()
    truncated = False
    rows = sorted(rows, key=lambda row: row.get("created_at") or "", reverse=True)
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        created_at = _parse_timestamp(row.get("created_at"))
        if created_at is None or created_at < cutoff:
            continue
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
        candidate = analyses + [summary]
        if _context_size(candidate) > MAX_ADVISORY_CONTEXT_BYTES:
            truncated = True
            break
        analyses.append(summary)
        analysis_types.add(summary["analysis_type"])
        if len(analyses) >= MAX_ADVISORY_ANALYSES:
            truncated = len(rows or []) > len(analyses)
            break
    return {
        "status": "available",
        "lookback_days": ADVISORY_LOOKBACK_DAYS,
        "analysis_count": len(analyses),
        "truncated": truncated,
        "analyses": analyses,
    }


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
            "limitation_count": _bounded_length(
                data_quality.get("limitations") if isinstance(data_quality, Mapping) else None
            ),
            "missing_field_count": _bounded_length(
                data_quality.get("missing_fields") if isinstance(data_quality, Mapping) else None
            ),
        },
        "evidence": {
            "count": _bounded_length(evidence),
            "providers": _evidence_providers(evidence),
        },
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
    if analysis_type == "profit_taking_review":
        position = result.get("position_snapshot")
        decision = result.get("decision")
        if isinstance(position, Mapping):
            ticker = _safe_identifier(position.get("ticker"))
            if ticker:
                findings["tickers"] = [ticker]
            market = _safe_identifier(position.get("market"))
            if market:
                findings["market"] = market
        if isinstance(decision, Mapping):
            action = _safe_identifier(decision.get("action"))
            findings["actions"] = [action] if action in _SAFE_ACTIONS else []
            findings["confidence"] = _safe_scalar(decision.get("confidence"))
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
        if len(actions) >= MAX_ADVISORY_ACTIONS:
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


def _evidence_providers(evidence: Any) -> list[str]:
    if not isinstance(evidence, list):
        return []
    providers = []
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        provider = _safe_identifier(item.get("provider"))
        if provider and provider not in providers:
            providers.append(provider)
        if len(providers) >= MAX_ADVISORY_PROVIDERS:
            break
    return providers


def _bounded_length(value: Any) -> int:
    return min(len(value), MAX_ADVISORY_ANALYSES) if isinstance(value, list) else 0


def _safe_identifier(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    compact = "".join(
        character
        for character in value
        if character.isascii() and (character.isalnum() or character in "._:-")
    )
    return compact[:80] or None


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
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _context_size(analyses: list[dict[str, Any]]) -> int:
    return len(
        json.dumps(
            {
                "status": "available",
                "lookback_days": ADVISORY_LOOKBACK_DAYS,
                "analysis_count": len(analyses),
                "truncated": False,
                "analyses": analyses,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
