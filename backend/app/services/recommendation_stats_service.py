"""추천 성과 통계와 신뢰도 보정(calibrated confidence) 계산.

recommendation_cycles에 쌓인 실측 결과를 액션×호라이즌×점수밴드로 집계해
승률/평균 수익률/평균 보유일을 계산하고, 표본이 충분한 밴드에는
기술 점수 기반 신뢰도에 실측 승률 보정계수를 곱한다.
"""

from datetime import datetime, timezone
from typing import Any

from app.db.supabase_client import Repository
from app.utils.datetime import parse_iso_datetime
from app.utils.logging import log_external_failure

# 보정을 적용하기 위한 최소 종료 표본 수 (계획서 4-2)
MIN_SAMPLE_FOR_CALIBRATION = 30
# 승률 50%를 중립(계수 1.0)으로 보고, 계수는 과도한 왜곡을 막기 위해 클램프한다.
CALIBRATION_FACTOR_MIN = 0.6
CALIBRATION_FACTOR_MAX = 1.3
CLOSED_STATUSES = {"hit_target", "hit_stop", "expired", "ambiguous"}
SCORE_BANDS = ("under_60", "60s", "70s", "80_plus")

BAND_LABELS = {
    "under_60": "점수 60 미만",
    "60s": "점수 60대",
    "70s": "점수 70대",
    "80_plus": "점수 80 이상",
    "unknown": "점수 미기록",
}


def score_band(score: Any) -> str:
    if score is None:
        return "unknown"
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        return "unknown"
    if numeric < 60:
        return "under_60"
    if numeric < 70:
        return "60s"
    if numeric < 80:
        return "70s"
    return "80_plus"


def calibration_factor(win_rate: float) -> float:
    factor = 0.5 + float(win_rate)
    return max(CALIBRATION_FACTOR_MIN, min(CALIBRATION_FACTOR_MAX, factor))


def _average(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _holding_days(cycle: dict[str, Any]) -> float | None:
    started = parse_iso_datetime(cycle.get("started_at") or cycle.get("created_at"))
    closed = parse_iso_datetime(cycle.get("closed_at"))
    if started is None or closed is None:
        return None
    days = (closed - started).total_seconds() / 86400
    return days if days >= 0 else None


def _technical_score(cycle: dict[str, Any]) -> Any:
    score = cycle.get("technical_score")
    if score is not None:
        return score
    return (cycle.get("metadata") or {}).get("technical_score")


def _is_measurement_excluded(cycle: dict[str, Any]) -> bool:
    return bool((cycle.get("metadata") or {}).get("measurement_excluded"))


class RecommendationStatsService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def compute_stats(self, limit: int = 1000) -> dict[str, Any]:
        try:
            cycles = self.repository.list_recommendation_cycles(limit=limit)
        except Exception as exc:
            log_external_failure("recommendation_cycles", exc, {"operation": "compute_stats"})
            cycles = []
        groups: dict[tuple[str, str, str], dict[str, Any]] = {}
        closed_total = 0
        win_total = 0
        for cycle in cycles:
            if _is_measurement_excluded(cycle):
                continue
            status = str(cycle.get("status") or "")
            if status == "superseded":
                # 신호가 교체된 사이클은 결과가 아니므로 통계에서 제외한다.
                continue
            action = str(cycle.get("action") or "UNKNOWN")
            horizon = str(cycle.get("horizon") or "medium")
            band = score_band(_technical_score(cycle))
            key = (action, horizon, band)
            group = groups.setdefault(
                key,
                {
                    "action": action,
                    "horizon": horizon,
                    "score_band": band,
                    "score_band_label": BAND_LABELS.get(band, band),
                    "cycle_count": 0,
                    "closed_count": 0,
                    "win_count": 0,
                    "target_hit_count": 0,
                    "stop_hit_count": 0,
                    "other_closed_count": 0,
                    "_returns_5d": [],
                    "_returns_20d": [],
                    "_holding_days": [],
                },
            )
            group["cycle_count"] += 1
            if cycle.get("return_after_5d") is not None:
                group["_returns_5d"].append(float(cycle["return_after_5d"]))
            if cycle.get("return_after_20d") is not None:
                group["_returns_20d"].append(float(cycle["return_after_20d"]))
            if status in CLOSED_STATUSES:
                group["closed_count"] += 1
                closed_total += 1
                if status == "hit_target":
                    group["win_count"] += 1
                    win_total += 1
                    group["target_hit_count"] += 1
                elif status == "hit_stop":
                    group["stop_hit_count"] += 1
                else:
                    group["other_closed_count"] += 1
                holding = _holding_days(cycle)
                if holding is not None:
                    group["_holding_days"].append(holding)

        rows = []
        for group in groups.values():
            closed = group["closed_count"]
            win_rate = (group["win_count"] / closed) if closed else None
            calibrated = closed >= MIN_SAMPLE_FOR_CALIBRATION and win_rate is not None
            rows.append(
                {
                    "action": group["action"],
                    "horizon": group["horizon"],
                    "score_band": group["score_band"],
                    "score_band_label": group["score_band_label"],
                    "cycle_count": group["cycle_count"],
                    "closed_count": closed,
                    "win_count": group["win_count"],
                    "win_rate": round(win_rate, 4) if win_rate is not None else None,
                    "target_hit_count": group["target_hit_count"],
                    "stop_hit_count": group["stop_hit_count"],
                    "other_closed_count": group["other_closed_count"],
                    "target_hit_frequency": (
                        round(group["target_hit_count"] / closed, 4) if closed else None
                    ),
                    "stop_hit_frequency": (
                        round(group["stop_hit_count"] / closed, 4) if closed else None
                    ),
                    "other_closed_frequency": (
                        round(group["other_closed_count"] / closed, 4) if closed else None
                    ),
                    "avg_return_5d": _average(group["_returns_5d"]),
                    "avg_return_20d": _average(group["_returns_20d"]),
                    "avg_holding_days": _average(group["_holding_days"]),
                    "calibration_applied": calibrated,
                    "calibration_factor": (
                        round(calibration_factor(win_rate), 4) if calibrated else None
                    ),
                }
            )
        rows.sort(key=lambda row: (-row["closed_count"], row["action"], row["horizon"]))
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "min_sample_for_calibration": MIN_SAMPLE_FOR_CALIBRATION,
            "totals": {
                "cycle_count": sum(row["cycle_count"] for row in rows),
                "closed_count": closed_total,
                "win_count": win_total,
                "win_rate": round(win_total / closed_total, 4) if closed_total else None,
            },
            "groups": rows,
        }


class ConfidenceCalibrator:
    """compute_stats 결과를 이용해 전략 신뢰도를 실측 승률로 보정한다."""

    def __init__(self, stats: dict[str, Any]) -> None:
        self._by_key = {
            (row["action"], row["horizon"], row["score_band"]): row
            for row in stats.get("groups", [])
        }

    @classmethod
    def from_repository(cls, repository: Repository) -> "ConfidenceCalibrator":
        return cls(RecommendationStatsService(repository).compute_stats())

    def calibrate(
        self,
        action: str,
        horizon: str,
        base_confidence: int,
        news_context_used: bool = False,
        technical_score: int | float | None = None,
    ) -> dict[str, Any]:
        """보정 결과와 산출 근거(기술/과거 승률/뉴스 기여)를 함께 반환한다."""
        band_score = technical_score if technical_score is not None else base_confidence
        band = score_band(band_score)
        group = self._by_key.get((action, horizon, band))
        detail: dict[str, Any] = {
            "technical_score": technical_score,
            "base_confidence": base_confidence,
            "technical_confidence": base_confidence,
            "score_band": band,
            "horizon": horizon,
            "news_context_used": news_context_used,
            "sample_size": group["closed_count"] if group else 0,
            "win_rate": group["win_rate"] if group else None,
            "outcome_sample_size": group["closed_count"] if group else 0,
            "target_hit_count": group["target_hit_count"] if group else 0,
            "stop_hit_count": group["stop_hit_count"] if group else 0,
            "other_closed_count": group["other_closed_count"] if group else 0,
            "target_hit_frequency": group["target_hit_frequency"] if group else None,
            "stop_hit_frequency": group["stop_hit_frequency"] if group else None,
            "other_closed_frequency": group["other_closed_frequency"] if group else None,
            "calibrated": False,
            "calibration_factor": None,
        }
        if group and group["calibration_applied"]:
            factor = calibration_factor(group["win_rate"])
            calibrated_confidence = int(round(max(0, min(100, base_confidence * factor))))
            detail["calibrated"] = True
            detail["calibration_factor"] = round(factor, 4)
            return {"confidence": calibrated_confidence, "detail": detail}
        return {"confidence": base_confidence, "detail": detail}
