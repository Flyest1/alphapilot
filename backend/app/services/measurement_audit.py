"""Pure original-decision audit; never rewrites operating recommendation outcomes."""

from collections import Counter
from math import isfinite
from typing import Any

import pandas as pd

from app.services.report.tracking import evaluate_barriers, horizon_days, trading_timestamp


def audit_recommendations(
    cycles: list[dict[str, Any]], histories: dict[str, pd.DataFrame], *, as_of: str
) -> dict[str, Any]:
    cutoff = pd.Timestamp(as_of).date()
    observations = []
    reasons: Counter = Counter()
    for cycle in cycles:
        result: dict[str, Any] = {"cycle_id": cycle.get("id"), "stored_status": cycle.get("status")}
        metadata = cycle.get("metadata")
        original = metadata.get("original_decision") if isinstance(metadata, dict) else None
        reason = None
        if not isinstance(original, dict):
            reason = "missing_original_decision"
        else:
            try:
                stamp = pd.Timestamp(original["decision_at"])
                if pd.isna(stamp):
                    raise ValueError("Missing decision date")
                start = stamp.date()
                reference = float(original["reference_price"])
                if not isfinite(reference) or reference <= 0 or start > cutoff:
                    raise ValueError("Invalid original reference")
                if original.get("horizon") not in {"short", "medium", "long"}:
                    raise ValueError("Unknown horizon")
                if original.get("action") not in {"BUY", "HOLD", "WATCH", "SELL", "REDUCE"}:
                    raise ValueError("Unknown action")
            except (KeyError, TypeError, ValueError):
                reason = "invalid_original_decision"
        frame = histories.get(original.get("ticker")) if isinstance(original, dict) else None
        if reason is None and (
            not isinstance(frame, pd.DataFrame) or frame.empty or "close" not in frame
        ):
            reason = "missing_price_history"
        if reason is None and (
            not isinstance(frame.index, pd.DatetimeIndex) or frame.index.hasnans
        ):
            reason = "invalid_price_sessions"
        if reason is None:
            frame = frame.sort_index().copy()
            frame = frame[frame.index.date <= cutoff]
            if frame.empty or not any(frame.index.date <= start):
                reason = "missing_history_anchor"
            elif pd.Index(frame.index.date).has_duplicates:
                reason = "duplicate_price_sessions"
        if reason is None:
            future = frame[frame.index.date > start]
            columns = [key for key in ("close", "high", "low") if key in future]
            numeric = future[columns].apply(pd.to_numeric, errors="coerce")
            if (
                not numeric.apply(
                    lambda column: column.map(lambda value: isfinite(value) and value > 0)
                )
                .all()
                .all()
            ):
                reason = "invalid_price_history"
            elif not future.empty and not {"high", "low"}.issubset(future.columns):
                reason = "missing_barrier_prices"
            elif (
                not future.empty
                and not (
                    (numeric["low"] <= numeric["close"]) & (numeric["close"] <= numeric["high"])
                ).all()
            ):
                reason = "invalid_price_history"
        if reason is None:
            target, stop = original.get("target_price"), original.get("stop_loss")
            try:
                target = float(target) if target is not None else None
                stop = float(stop) if stop is not None else None
                if any(
                    value is not None and (not isfinite(value) or value <= 0)
                    for value in (target, stop)
                ):
                    raise ValueError("Invalid barrier")
                is_short = original["action"] in {"SELL", "REDUCE"}
                if target is not None and (
                    target >= reference if is_short else target <= reference
                ):
                    raise ValueError("Invalid target direction")
                if stop is not None and (stop <= reference if is_short else stop >= reference):
                    raise ValueError("Invalid stop direction")
            except (ValueError, TypeError):
                reason = "invalid_original_barriers"
        if reason is not None:
            reasons[reason] += 1
            result.update(status="excluded", exclusion_reason=reason)
        else:
            horizon = horizon_days(original["horizon"])
            terminal = evaluate_barriers(original["action"], target, stop, future.iloc[:horizon])
            result["status"] = (
                terminal[0] if terminal else ("expired" if len(future) >= horizon else "pending")
            )
            result["closed_at"] = (
                terminal[1]
                if terminal
                else (
                    trading_timestamp(future.index[horizon - 1]) if len(future) >= horizon else None
                )
            )
            result["forward_returns_pct"] = {
                str(days): round((float(future.iloc[days - 1]["close"]) / reference - 1) * 100, 4)
                for days in (1, 5, 20, 60)
                if len(future) >= days
            }
        observations.append(result)
    return {
        "policy_version": "original_decision_audit_v1",
        "as_of": cutoff.isoformat(),
        "research_only": True,
        "measurement_quality": "provisional_no_exchange_calendar",
        "promotion_permitted": False,
        "sample_count": len(cycles),
        "evaluated_count": len(cycles) - sum(reasons.values()),
        "excluded_reasons": dict(reasons),
        "changed_status_count": sum(
            row["status"] != row["stored_status"]
            for row in observations
            if row["status"] not in {"excluded", "pending"}
        ),
        "limitations": [
            "Legacy originals are not inferred from mutable latest recommendation fields.",
            "No exchange calendar: internal missing sessions cannot be certified complete.",
            "Daily bars start after decision date; intraday execution and costs are not modeled.",
            "Prices must use the same adjustment and currency basis as original barriers.",
        ],
        "observations": observations,
    }
