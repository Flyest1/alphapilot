import json
from datetime import date, timedelta

import pandas as pd
import pytest

from app.services.signal_research_service import (
    HIGH_CORRELATION_THRESHOLD,
    SignalResearchService,
    evaluate_signal_research,
)


def _samples(days: int = 30) -> list[dict[str, object]]:
    rows = []
    start = date(2025, 1, 1)
    tickers = ("AAA", "BBB", "CCC", "DDD")
    technical_scores = (60.0, 70.0, 50.0, 80.0)
    signal_values = (4.0, 3.0, 2.0, 1.0)
    for day in range(days):
        for index, ticker in enumerate(tickers):
            signal = signal_values[index]
            rows.append(
                {
                    "date": (start + timedelta(days=day)).isoformat(),
                    "label_end_date": (start + timedelta(days=day)).isoformat(),
                    "ticker": ticker,
                    "market": "KR" if index % 2 == 0 else "US",
                    "regime": "bull" if day % 2 == 0 else "sideways",
                    "technical_score": technical_scores[index],
                    "net_return_pct": signal * 2 - 4,
                    "signals": {"relative_strength": signal},
                }
            )
    return rows


def _signal(result: dict[str, object], name: str) -> dict[str, object]:
    return next(item for item in result["signals"] if item["signal"] == name)


def test_evaluation_returns_research_only_json_safe_diagnostics() -> None:
    result = evaluate_signal_research(_samples())
    signal = _signal(result, "relative_strength")

    assert result["research_only"] is True
    assert result["adoption_permitted"] is False
    assert "not investment advice" in result["disclaimer"]
    assert result["sample_count"] == 120
    assert result["cohort_count"] == 30
    assert result["walk_forward"]["valid_fold_count"] == 3
    assert signal["status"] == "candidate"
    assert signal["standalone_spread"]["net_return_spread_pct"] == 6.0
    assert signal["incremental_rank_combination"]["combined_rank"]["sample_count"] == 60
    assert len(signal["consistency"]["by_market"]) == 2
    assert len(signal["consistency"]["walk_forward_folds"]) == 3
    json.dumps(result)


def test_high_correlation_with_existing_score_and_other_signal_is_rejected() -> None:
    samples = _samples()
    for sample in samples:
        signals = sample["signals"]
        signals["score_clone"] = sample["technical_score"]
        signals["relative_strength_clone"] = signals["relative_strength"] * 10

    result = SignalResearchService().evaluate(samples)
    score_clone = _signal(result, "score_clone")
    original = _signal(result, "relative_strength")

    assert score_clone["status"] == "rejected"
    assert "high_correlation_with_technical_score" in score_clone["reasons"]
    assert original["status"] == "rejected"
    assert "relative_strength_clone" in original["redundancy"]["highly_correlated_signals"]
    correlation = next(
        row
        for row in original["redundancy"]["signal_correlations"]
        if row["signal"] == "relative_strength_clone"
    )
    assert correlation["spearman"] == pytest.approx(1.0)
    assert correlation["high_correlation"] is (
        abs(correlation["spearman"]) >= HIGH_CORRELATION_THRESHOLD
    )


def test_spearman_uses_average_ranks_without_optional_scipy_dependency() -> None:
    first = pd.Series([1.0, 2.0, 2.0, 4.0])
    second = pd.Series([10.0, 20.0, 20.0, 40.0])
    inverse = pd.Series([40.0, 20.0, 20.0, 10.0])
    non_monotonic = pd.Series([5.0, 1.0, 2.0, 4.0])

    assert SignalResearchService._spearman(first, second) == pytest.approx(1.0)
    assert SignalResearchService._spearman(first, inverse) == pytest.approx(-1.0)
    assert SignalResearchService._spearman(first, non_monotonic) == pytest.approx(-0.316227766)


def test_spearman_omits_nan_pairs_and_rejects_undefined_inputs() -> None:
    first = pd.Series([1.0, float("nan"), 3.0, 4.0])
    second = pd.Series([1.0, 2.0, 4.0, 3.0])

    assert SignalResearchService._spearman(first, second) == pytest.approx(0.5)
    assert SignalResearchService._spearman(pd.Series([1.0]), pd.Series([2.0])) is None
    assert SignalResearchService._spearman(pd.Series([1.0, 1.0]), pd.Series([1.0, 2.0])) is None
    assert (
        SignalResearchService._spearman(
            pd.Series([float("nan"), float("nan")]),
            pd.Series([1.0, 2.0]),
        )
        is None
    )


def test_constant_nan_and_insufficient_samples_are_rejected_with_reasons() -> None:
    samples = _samples(days=2)
    for sample in samples:
        sample["signals"] = {"constant": 1.0, "missing": float("nan")}

    result = evaluate_signal_research(samples)
    constant = _signal(result, "constant")
    missing = _signal(result, "missing")

    assert constant["status"] == "rejected"
    assert "constant_signal" in constant["reasons"]
    assert "insufficient_samples:8/30" in constant["reasons"]
    assert "insufficient_cohorts:2/30" in constant["reasons"]
    assert "insufficient_market_samples" in constant["reasons"]
    assert any(
        reason.startswith("insufficient_walk_forward_folds") for reason in constant["reasons"]
    )
    assert missing["status"] == "rejected"
    assert "no_finite_signal_values" in missing["reasons"]


def test_rank_selection_never_uses_future_return_label() -> None:
    original = _samples()
    altered = _samples()
    for sample in altered:
        if sample["signals"]["relative_strength"] == 1.0:
            sample["net_return_pct"] = 1_000.0

    first = _signal(evaluate_signal_research(original), "relative_strength")
    second = _signal(evaluate_signal_research(altered), "relative_strength")

    assert first["standalone_spread"]["top_net_return_pct"] == 4.0
    assert second["standalone_spread"]["top_net_return_pct"] == 4.0
    assert (
        first["incremental_rank_combination"]["combined_rank"]["turnover_proxy"]
        == second["incremental_rank_combination"]["combined_rank"]["turnover_proxy"]
    )


def test_explicit_walk_forward_folds_are_deterministic_and_require_valid_test_samples() -> None:
    samples = _samples()
    folds = [
        {"test_indices": list(range(0, 40))},
        {"test_indices": list(range(40, 80))},
        {"test_indices": list(range(80, 120))},
    ]

    first = evaluate_signal_research(samples, walk_forward_folds=folds)
    second = evaluate_signal_research(samples, walk_forward_folds=folds)
    signal = _signal(first, "relative_strength")

    assert first == second
    assert first["walk_forward"]["valid_fold_count"] == 3
    assert signal["consistency"]["walk_forward_direction"]["valid_fold_count"] == 3


def test_input_contract_and_quantile_are_validated() -> None:
    with pytest.raises(ValueError, match="missing required fields"):
        evaluate_signal_research([{"date": "2025-01-01"}])
    with pytest.raises(ValueError, match="quantile"):
        evaluate_signal_research(_samples(), quantile=0.6)


def test_overlapping_labels_do_not_count_as_independent_cohorts() -> None:
    samples = _samples()
    common_end = samples[-1]["date"]
    for sample in samples:
        sample["label_end_date"] = common_end

    result = evaluate_signal_research(samples)
    signal = _signal(result, "relative_strength")

    assert result["cohort_count"] == 1
    assert "insufficient_cohorts:1/30" in signal["reasons"]


def test_test_indices_keep_original_input_meaning_and_fold_dates_cannot_overlap() -> None:
    samples = list(reversed(_samples()))
    result = evaluate_signal_research(
        samples,
        walk_forward_folds=[{"test_indices": list(range(40))}],
    )

    assert result["walk_forward"]["folds"][0]["start_date"] == "2025-01-21"
    assert result["walk_forward"]["folds"][0]["end_date"] == "2025-01-30"

    with pytest.raises(ValueError, match="must not overlap"):
        evaluate_signal_research(
            _samples(),
            walk_forward_folds=[
                {"test_dates": ["2025-01-01", "2025-01-02"]},
                {"test_dates": ["2025-01-02", "2025-01-03"]},
            ],
        )


def test_candidate_gate_rejects_turnover_and_max_drawdown_worsening() -> None:
    status, reasons = SignalResearchService()._status(
        total_count=120,
        cohort_count=30,
        signal_values=pd.Series([1.0, 2.0]),
        technical_score_spearman=0.1,
        redundant_with=[],
        valid_fold_results=[
            {"sample_count": 20, "direction": "positive"},
            {"sample_count": 20, "direction": "positive"},
            {"sample_count": 20, "direction": "positive"},
        ],
        standalone={"net_return_spread_pct": 1.0},
        incremental={
            "baseline_technical_score": {"max_drawdown_pct": -2.0},
            "combined_rank": {"max_drawdown_pct": -5.0},
            "incremental": {"expected_value_pct": 1.0, "turnover_proxy": 0.1},
        },
        market_summary=[{"sample_count": 40, "direction": "positive"}],
        regime_summary=[
            {"sample_count": 40, "direction": "positive"},
            {"sample_count": 40, "direction": "positive"},
        ],
    )

    assert status == "rejected"
    assert "turnover_worsened" in reasons
    assert "max_drawdown_worsened" in reasons
