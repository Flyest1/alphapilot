from app.db.supabase_client import InMemoryRepository
from app.services.recommendation_stats_service import (
    ConfidenceCalibrator,
    MIN_SAMPLE_FOR_CALIBRATION,
    RecommendationStatsService,
    calibration_factor,
    score_band,
)


def make_cycle(repo, status="hit_target", confidence=75, **overrides):
    technical_score = overrides.pop("technical_score", confidence)
    data = {
        "report_type": "domestic",
        "ticker": overrides.pop("ticker", "005930"),
        "name": "Samsung",
        "action": overrides.pop("action", "BUY"),
        "horizon": overrides.pop("horizon", "medium"),
        "status": status,
        "reference_price": 100,
        "technical_score": technical_score,
        "base_confidence": overrides.pop("base_confidence", confidence),
        "calibrated_confidence": overrides.pop("calibrated_confidence", confidence),
        "metadata": overrides.pop("metadata", {}),
        "started_at": "2026-01-01T00:00:00+00:00",
        **overrides,
    }
    if status in {"hit_target", "hit_stop", "expired"}:
        data.setdefault("closed_at", "2026-01-15T00:00:00+00:00")
    return repo.create_recommendation_cycle(data)


def test_score_band_boundaries():
    assert score_band(None) == "unknown"
    assert score_band(59.9) == "under_60"
    assert score_band(60) == "60s"
    assert score_band(69) == "60s"
    assert score_band(70) == "70s"
    assert score_band(80) == "80_plus"


def test_calibration_factor_is_clamped():
    assert calibration_factor(0.5) == 1.0
    assert calibration_factor(0.9) == 1.3  # 0.5 + 0.9 = 1.4 → 상한 1.3
    assert calibration_factor(0.0) == 0.6  # 0.5 + 0.0 = 0.5 → 하한 0.6


def test_compute_stats_groups_by_action_horizon_and_band():
    repo = InMemoryRepository()
    for _ in range(3):
        make_cycle(repo, status="hit_target", confidence=75)
    make_cycle(repo, status="hit_stop", confidence=75, return_after_20d=-5)
    make_cycle(repo, status="active", confidence=75, return_after_5d=2)
    make_cycle(repo, status="superseded", confidence=75)  # 통계 제외
    make_cycle(repo, status="hit_target", confidence=85, action="WATCH")

    stats = RecommendationStatsService(repo).compute_stats()
    buy_group = next(
        row
        for row in stats["groups"]
        if row["action"] == "BUY" and row["horizon"] == "medium" and row["score_band"] == "70s"
    )

    assert buy_group["cycle_count"] == 5  # superseded 제외, active 포함
    assert buy_group["closed_count"] == 4
    assert buy_group["win_count"] == 3
    assert buy_group["win_rate"] == 0.75
    assert buy_group["target_hit_count"] == 3
    assert buy_group["stop_hit_count"] == 1
    assert buy_group["other_closed_count"] == 0
    assert buy_group["target_hit_frequency"] == 0.75
    assert buy_group["stop_hit_frequency"] == 0.25
    assert buy_group["other_closed_frequency"] == 0
    assert buy_group["avg_return_20d"] == -5
    assert buy_group["avg_holding_days"] == 14
    assert buy_group["calibration_applied"] is False  # 표본 30 미만
    assert stats["totals"]["closed_count"] == 5
    assert stats["min_sample_for_calibration"] == MIN_SAMPLE_FOR_CALIBRATION


def test_compute_stats_uses_raw_technical_score_and_legacy_metadata_only():
    repo = InMemoryRepository()
    make_cycle(
        repo,
        confidence=95,
        technical_score=65,
        calibrated_confidence=95,
        ticker="RAW",
    )
    make_cycle(
        repo,
        confidence=95,
        technical_score=None,
        metadata={"technical_score": 75, "confidence": 95},
        ticker="LEGACY",
    )
    make_cycle(
        repo,
        confidence=95,
        technical_score=None,
        metadata={"confidence": 95},
        ticker="UNKNOWN",
    )

    stats = RecommendationStatsService(repo).compute_stats()
    groups = {row["score_band"]: row for row in stats["groups"]}

    assert groups["60s"]["cycle_count"] == 1
    assert groups["70s"]["cycle_count"] == 1
    assert groups["unknown"]["cycle_count"] == 1
    assert "80_plus" not in groups


def test_ambiguous_is_closed_but_not_a_win_and_sell_target_is_favorable():
    repo = InMemoryRepository()
    make_cycle(repo, status="hit_target", action="SELL", technical_score=40, ticker="SELL-WIN")
    make_cycle(repo, status="ambiguous", action="SELL", technical_score=40, ticker="SELL-AMB")

    stats = RecommendationStatsService(repo).compute_stats()
    group = next(row for row in stats["groups"] if row["action"] == "SELL")

    assert group["closed_count"] == 2
    assert group["win_count"] == 1
    assert group["win_rate"] == 0.5
    assert group["target_hit_count"] == 1
    assert group["stop_hit_count"] == 0
    assert group["other_closed_count"] == 1
    assert group["other_closed_frequency"] == 0.5


def test_compute_stats_excludes_measurement_quarantined_cycles():
    repo = InMemoryRepository()
    make_cycle(repo, status="hit_target", ticker="INCLUDED")
    make_cycle(
        repo,
        status="hit_target",
        ticker="EXCLUDED",
        metadata={
            "measurement_excluded": True,
            "measurement_exclusion_reason": "invalid_short_barrier_layout",
            "measurement_policy_version": "short_barrier_layout_v1",
        },
    )

    stats = RecommendationStatsService(repo).compute_stats()

    assert stats["totals"] == {
        "cycle_count": 1,
        "closed_count": 1,
        "win_count": 1,
        "win_rate": 1.0,
    }


def test_calibrator_applies_factor_only_with_enough_samples():
    repo = InMemoryRepository()
    # 70대 밴드 BUY/medium: 종료 30건, 승률 80% → 계수 1.3
    for index in range(30):
        make_cycle(
            repo,
            status="hit_target" if index < 24 else "hit_stop",
            confidence=75,
            ticker=f"T{index:03d}",
        )
    calibrator = ConfidenceCalibrator.from_repository(repo)

    calibrated = calibrator.calibrate("BUY", "medium", 75, news_context_used=True)
    untouched = calibrator.calibrate("BUY", "medium", 85)  # 80+ 밴드는 표본 없음

    assert calibrated["confidence"] == 98  # 75 × 1.3
    assert calibrated["detail"]["calibrated"] is True
    assert calibrated["detail"]["sample_size"] == 30
    assert calibrated["detail"]["win_rate"] == 0.8
    assert calibrated["detail"]["outcome_sample_size"] == 30
    assert calibrated["detail"]["target_hit_frequency"] == 0.8
    assert calibrated["detail"]["stop_hit_frequency"] == 0.2
    assert calibrated["detail"]["news_context_used"] is True
    assert untouched["confidence"] == 85
    assert untouched["detail"]["calibrated"] is False
    assert untouched["detail"]["sample_size"] == 0


def test_calibrator_lowers_confidence_for_losing_bands():
    repo = InMemoryRepository()
    for index in range(30):
        make_cycle(
            repo,
            status="hit_target" if index < 6 else "hit_stop",  # 승률 20%
            confidence=65,
            ticker=f"L{index:03d}",
        )
    calibrator = ConfidenceCalibrator.from_repository(repo)

    result = calibrator.calibrate("BUY", "medium", 65)

    assert result["confidence"] == 46  # 65 × 0.7
    assert result["detail"]["calibration_factor"] == 0.7


def test_calibrator_selects_group_with_raw_score_not_base_confidence():
    repo = InMemoryRepository()
    for index in range(30):
        make_cycle(
            repo,
            status="hit_target" if index < 24 else "hit_stop",
            confidence=95,
            technical_score=65,
            ticker=f"R{index:03d}",
        )
    calibrator = ConfidenceCalibrator.from_repository(repo)

    result = calibrator.calibrate(
        "BUY",
        "medium",
        base_confidence=50,
        technical_score=65,
    )

    assert result["confidence"] == 65
    assert result["detail"]["technical_score"] == 65
    assert result["detail"]["base_confidence"] == 50
    assert result["detail"]["score_band"] == "60s"
