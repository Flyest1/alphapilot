from datetime import date, timedelta

import pandas as pd
import pytest

from app.services.backtest_validation import (
    aggregate_validation_results,
    calculate_baseline_returns,
    classify_market_regime,
    create_walk_forward_folds,
)


def _frame(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": closes})


def _samples(count: int) -> list[dict[str, str]]:
    start = date(2026, 1, 1)
    return [{"date": (start + timedelta(days=index)).isoformat()} for index in range(count)]


def test_market_regime_uses_only_history_through_as_of_position():
    prefix = [100 + index for index in range(25)]
    first = _frame(prefix + [1_000, 1])
    second = _frame(prefix + [1, 1_000])

    assert classify_market_regime(first, 24) == "bull"
    assert classify_market_regime(second, 24) == "bull"


@pytest.mark.parametrize(
    ("closes", "expected"),
    [
        ([100 + index for index in range(30)], "bull"),
        ([130 - index for index in range(30)], "bear"),
        ([100.0] * 30, "sideways"),
        ([100, 120] * 15, "high_volatility"),
    ],
)
def test_market_regime_boundaries(closes, expected):
    assert classify_market_regime(_frame(closes)) == expected


def test_walk_forward_folds_purge_forward_label_overlap():
    result = create_walk_forward_folds(_samples(18), train_size=6, test_size=3, forward_days=2)

    assert result["reason"] is None
    assert result["folds"][0]["train_indices"] == list(range(6))
    assert result["folds"][0]["purged_indices"] == [6, 7]
    assert result["folds"][0]["test_indices"] == [8, 9, 10]
    assert result["folds"][1]["train_indices"] == list(range(9))
    assert result["folds"][1]["purged_indices"] == [9, 10]
    assert result["folds"][1]["test_indices"] == [11, 12, 13]


def test_walk_forward_returns_reason_when_samples_are_insufficient():
    result = create_walk_forward_folds(_samples(10), train_size=6, test_size=3, forward_days=2)

    assert result["folds"] == []
    assert result["reason"] == "insufficient decision dates: need at least 11, received 10"


def test_walk_forward_rejects_unsorted_samples():
    samples = _samples(12)
    samples[3], samples[4] = samples[4], samples[3]

    with pytest.raises(ValueError, match="chronologically"):
        create_walk_forward_folds(samples, train_size=5, test_size=3, forward_days=1)


def test_aggregate_validation_results_groups_deterministically():
    rows = aggregate_validation_results(
        [
            {"action": "BUY", "market": "US", "regime": "bull", "net_return": 0.1},
            {"action": "BUY", "market": "US", "regime": "bull", "net_return": -0.02},
            {"action": "SELL", "market": "KR", "regime": "bear", "net_return": 0.03},
        ]
    )

    assert rows == [
        {
            "action": "BUY",
            "market": "US",
            "regime": "bull",
            "sample_count": 2,
            "avg_net_return": 0.04,
        },
        {
            "action": "SELL",
            "market": "KR",
            "regime": "bear",
            "sample_count": 1,
            "avg_net_return": 0.03,
        },
    ]


def test_baselines_use_only_pre_decision_values_for_signals():
    prefix = [float(value) for value in range(80, 101)]
    rising_future = _frame(prefix + [110, 120, 130])
    altered_later_future = _frame(prefix + [90, 70, 130])

    first = calculate_baseline_returns(rising_future, 20, 3)
    second = calculate_baseline_returns(altered_later_future, 20, 3)

    assert first["sma_direction"] == second["sma_direction"] == 1
    assert first["momentum_direction"] == second["momentum_direction"] == 1
    assert first["buy_and_hold"] == pytest.approx(130 / 110 - 1)
    assert first["sma_trend"] == pytest.approx(130 / 110 - 1)
    assert first["simple_momentum"] == pytest.approx(130 / 110 - 1)
    assert first["sma_direction"] == 1
    assert first["momentum_direction"] == 1


def test_baselines_apply_short_direction_when_trends_are_falling():
    frame = _frame([float(value) for value in range(120, 99, -1)] + [95, 90, 80])

    result = calculate_baseline_returns(frame, 20, 3)

    assert result["buy_and_hold"] == pytest.approx(80 / 95 - 1)
    assert result["sma_trend"] == pytest.approx(1 - 80 / 95)
    assert result["simple_momentum"] == pytest.approx(1 - 80 / 95)


def test_baselines_reject_insufficient_history():
    with pytest.raises(ValueError, match="pre-decision"):
        calculate_baseline_returns(_frame([100.0] * 25), 10, 3)


def test_walk_forward_keeps_same_date_rows_together_and_purges_overlapping_labels():
    samples = [
        {"date": "2026-01-01", "label_end_date": "2026-01-02", "ticker": "A"},
        {"date": "2026-01-01", "label_end_date": "2026-01-02", "ticker": "B"},
        {"date": "2026-01-02", "label_end_date": "2026-01-06", "ticker": "A"},
        {"date": "2026-01-03", "label_end_date": "2026-01-07", "ticker": "A"},
        {"date": "2026-01-04", "label_end_date": "2026-01-08", "ticker": "A"},
        {"date": "2026-01-05", "label_end_date": "2026-01-09", "ticker": "A"},
    ]

    result = create_walk_forward_folds(
        samples,
        train_size=2,
        test_size=2,
        forward_days=1,
    )

    fold = result["folds"][0]
    assert fold["test_indices"] == [4, 5]
    assert set(fold["train_indices"]).isdisjoint(fold["test_indices"])
    assert {samples[index]["date"] for index in fold["test_indices"]} == {
        "2026-01-04",
        "2026-01-05",
    }
    assert 2 in fold["purged_indices"]
