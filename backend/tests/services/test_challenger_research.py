from copy import deepcopy

import pandas as pd
import pytest

from app.services.challenger_research import run_challenger_research


def test_challenger_uncertainty_uses_heldout_cohorts_only():
    result = run_challenger_research(payload())
    for experiment in result["experiments"]:
        if experiment["model"] in {"trend_regime_filter", "entry_hold_hysteresis"}:
            uncertainty = experiment["uncertainty_vs_champion"]
            assert (
                uncertainty["cohort_count"] == experiment["paired_test_vs_champion"]["cohort_count"]
            )
            assert uncertainty["status"] == "insufficient_data"
            assert uncertainty["interval_pct"] is None


def payload():
    dates = pd.bdate_range("2020-01-01", periods=410)
    return {
        "as_of": dates[-1].date().isoformat(),
        "costs": {"fee_rate_pct": 0.1, "kr_tax_rate_pct": 0.2, "fx_spread_pct": 0.1},
        "assets": [
            {
                "ticker": "AAPL",
                "market": "US",
                "prices": [
                    {
                        "date": date.date().isoformat(),
                        "open": 100 + i * 0.1,
                        "high": 101 + i * 0.1,
                        "low": 99 + i * 0.1,
                        "close": 100.5 + i * 0.1,
                        "volume": 1000000 + i * 10000,
                    }
                    for i, date in enumerate(dates)
                ],
            }
        ],
    }


def test_research_reports_every_fixed_experiment_with_no_promotion_or_annualization():
    data = payload()
    before = deepcopy(data)
    result = run_challenger_research(data)
    assert len(result["experiments"]) == 16
    assert result["adoption_permitted"] is False
    assert result["conclusion"] == "insufficient_evidence"
    assert result["folds"]
    assert len(result["input_sha256"]) == len(result["config_sha256"]) == 64
    assert result["code_sha256"]
    assert "annualized" not in str(result["experiments"])
    assert data == before


def test_future_prices_do_not_change_earlier_signals_or_completed_labels():
    data = payload()
    original = run_challenger_research(data)
    changed = deepcopy(data)
    boundary = changed["assets"][0]["prices"][360]["date"]
    for row in changed["assets"][0]["prices"][360:]:
        for column in ("open", "high", "low", "close"):
            row[column] *= 2
    perturbed = run_challenger_research(changed)
    for before, after in zip(original["experiments"], perturbed["experiments"]):

        def early(rows):
            return [row for row in rows if row["label_end_date"] < boundary]

        assert early(before["observations"]) == early(after["observations"])


def test_cost_stress_reduces_returns_and_delay_moves_entry_one_session():
    result = run_challenger_research(payload())
    variants = {
        (r["model"], r["cost_multiplier"], r["delay_sessions"]): r for r in result["experiments"]
    }
    base = variants[("entry_hold_hysteresis", 1, 0)]["observations"]
    stress = variants[("entry_hold_hysteresis", 2, 0)]["observations"]
    active = [(a, b) for a, b in zip(base, stress) if a["status"] == "evaluated"]
    assert active
    for a, b in active:
        assert b["gross_return_pct"] == a["gross_return_pct"]
        assert b["net_return_pct"] < a["net_return_pct"]
    delayed = variants[("entry_hold_hysteresis", 1, 1)]["observations"]
    assert all(a["entry_date"] < b["entry_date"] for a, b in zip(base, delayed))


def test_invalid_asset_retains_all_failed_experiments():
    data = payload()
    data["assets"][0]["market"] = "UNKNOWN"
    result = run_challenger_research(data)
    assert len(result["experiments"]) == 16
    assert all(row["status"] == "unavailable" for row in result["experiments"])
    assert result["unsupported_evidence"]


@pytest.mark.parametrize("field,value", [("fee_rate_pct", -1), ("fx_spread_pct", float("nan"))])
def test_invalid_cost_configuration_is_rejected(field, value):
    data = payload()
    data["costs"][field] = value
    with pytest.raises(ValueError):
        run_challenger_research(data)


def test_date_cohort_purge_uses_latest_label_end_for_all_assets():
    from app.services.challenger_research import _validation

    decisions = [
        {"date": f"2020-01-{day:02}", "label_end_date": f"2020-01-{day + 1:02}"}
        for day in range(1, 14)
    ]
    decisions.append({"date": "2020-01-06", "label_end_date": "2020-01-12"})
    samples, validation = _validation(decisions)
    fold = validation["folds"][0]
    assert "2020-01-06" not in {samples[i]["date"] for i in fold["train_indices"]}
    assert all(
        samples[i]["label_end_date"] < fold["test_start_date"] for i in fold["train_indices"]
    )


def test_only_usable_matched_cohorts_count_as_champion_comparison():
    from app.services.challenger_research import _paired_summary, _summary

    champion = [
        {
            "date": "2020-01-01",
            "market": "US",
            "ticker": "A",
            "status": "evaluated",
            "net_return_pct": 5,
        }
    ]
    gap = [
        {
            "date": "2020-01-01",
            "market": "US",
            "ticker": "A",
            "status": "excluded",
            "reason": "entry_gap_outside_original_barriers",
        }
    ]
    assert _paired_summary(gap, champion)["cohort_count"] == 0
    assert _paired_summary(gap, champion)["mean_cohort_delta_pct"] is None
    assert _summary(gap)["status"] == "unavailable"
    improved = [{**champion[0], "net_return_pct": 7}]
    assert _paired_summary(improved, champion)["mean_cohort_delta_pct"] == 2


def test_returned_config_cannot_modify_preregistration():
    data = {"as_of": "2026-01-01", "assets": [], "costs": payload()["costs"]}
    result = run_challenger_research(data)
    result["config"]["hypotheses"].clear()
    assert len(run_challenger_research(data)["experiments"]) == 16


def test_causal_precomputed_daily_scores_match_pinned_champion_prefixes():
    from app.services.challenger_research import _daily_scores
    from app.services.technical_analysis_service import TechnicalAnalysisService

    frame = pd.DataFrame(payload()["assets"][0]["prices"]).set_index("date")
    frame.index = pd.to_datetime(frame.index)
    scores = _daily_scores(frame)
    champion = TechnicalAnalysisService()
    for position in (119, 120, 150, 300, 409):
        assert (
            scores[position] == champion.analyze("AAPL", frame.iloc[: position + 1]).technical_score
        )
