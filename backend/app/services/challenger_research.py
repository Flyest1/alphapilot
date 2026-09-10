"""Preregistered local sleeve comparison; no fitting, promotion, DB or network access."""

from collections import Counter, defaultdict
from copy import deepcopy
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import platform
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

from app.services.backtest_metrics import estimate_round_trip_cost_pct
from app.services.backtest_validation import classify_market_regime, create_walk_forward_folds
from app.services.report.tracking import evaluate_barriers
from app.services.strategy_service import StrategyService
from app.services.technical_analysis_service import TechnicalAnalysisService

CHAMPION_SOURCES = {
    "technical_analysis_service.py": (
        "d0799e4f7910b60f9bbff0c17be8e8a6b55fbc22e4142b88946b419a8fc6b109"
    ),
    "strategy_service.py": "a75658a257c1b163e7c132e1f1b6648404110961c269d4c98b76a1eac8bdf97f",
}
CONFIG = {
    "version": "fixed_challenger_sleeves_v1",
    "risk_profile": "balanced",
    "warmup_sessions": 120,
    "horizon_sessions": 20,
    "decision_step_sessions": 22,
    "train_cohorts": 6,
    "test_cohorts": 3,
    "embargo_cohorts": 1,
    "cost_multipliers": [1, 2],
    "extra_delay_sessions": [0, 1],
    "hypotheses": {
        "champion": "Pinned balanced technical BUY signals; other actions idle.",
        "trend_regime_filter": "Champion BUY, close>SMA120, regime not high_volatility.",
        "entry_hold_hysteresis": "Daily score>=80 enters eligible state; score<65 exits it.",
        "buy_and_hold_sleeve": "Unconditional long sleeve on identical sampled dates, no barriers.",
    },
    "hysteresis_entry": 80,
    "hysteresis_exit": 65,
    "minimum_test_cohorts": 30,
    "minimum_folds": 3,
}


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _code_hashes() -> dict[str, str]:
    root = Path(__file__).parent
    names = [
        *CHAMPION_SOURCES,
        "challenger_research.py",
        "backtest_metrics.py",
        "backtest_validation.py",
        "report/tracking.py",
    ]
    return {
        name: sha256((root / name).read_text(encoding="utf-8").encode()).hexdigest()
        for name in names
    }


def _frame(asset: dict[str, Any], cutoff: pd.Timestamp) -> pd.DataFrame:
    if asset.get("market") not in {"KR", "US"} or not asset.get("ticker"):
        raise ValueError("explicit_KR_or_US_market_and_ticker_required")
    frame = pd.DataFrame(asset["prices"]).set_index("date")
    frame.index = pd.to_datetime(frame.index, errors="raise", utc=True)
    if frame.index.isna().any() or frame.index.normalize().has_duplicates:
        raise ValueError("invalid_or_duplicate_session_dates")
    if not (frame.index == frame.index.normalize()).all():
        raise ValueError("daily_session_dates_required")
    frame = frame.sort_index().loc[lambda rows: rows.index <= cutoff]
    columns = ["open", "high", "low", "close", "volume"]
    frame = frame[columns].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(frame.to_numpy()).all() or (frame[columns[:-1]] <= 0).any().any():
        raise ValueError("invalid_prices")
    if (
        (frame.volume < 0).any()
        or (frame.high < frame[["open", "close", "low"]].max(axis=1)).any()
        or (frame.low > frame[["open", "close"]].min(axis=1)).any()
    ):
        raise ValueError("invalid_OHLCV")
    if len(frame) < 142:
        raise ValueError("insufficient_lookback_or_forward_history")
    return frame


def _daily_scores(frame: pd.DataFrame) -> list[int]:
    technical = TechnicalAnalysisService()
    # These pinned indicators use only trailing/expanding operations. Reusing
    # them keeps daily hysteresis linear rather than recomputing every prefix.
    indicators = technical.calculate_indicators(frame)
    return [
        (
            max(0, min(100, sum(technical.calculate_score_breakdown(row).values())))
            if position >= 119
            else 0
        )
        for position, (_, row) in enumerate(indicators.iterrows())
    ]


def _decisions(asset: dict[str, Any], frame: pd.DataFrame) -> list[dict[str, Any]]:
    technical, strategy = TechnicalAnalysisService(), StrategyService()
    rows, eligible = [], False
    scores = _daily_scores(frame)
    for position in range(119, len(frame) - 21):
        history = frame.iloc[: position + 1]
        score = scores[position]
        eligible = score >= 65 if eligible else score >= 80
        if (position - 119) % 22:
            continue
        analysis = technical.analyze(asset["ticker"], history)
        close = float(history.close.iloc[-1])
        decision = strategy.generate_strategy(
            asset, SimpleNamespace(is_stale=False, current_price=close), analysis, "balanced"
        )
        rows.append(
            {
                "date": frame.index[position].date().isoformat(),
                "label_end_date": frame.index[position + 21].date().isoformat(),
                "position": position,
                "score": score,
                "target": decision.target_price,
                "stop": decision.stop_loss,
                "champion_action": decision.action,
                "active": {
                    "champion": decision.action == "BUY",
                    "trend_regime_filter": decision.action == "BUY"
                    and close > float(history.close.tail(120).mean())
                    and classify_market_regime(history) != "high_volatility",
                    "entry_hold_hysteresis": eligible,
                    "buy_and_hold_sleeve": True,
                },
            }
        )
    return rows


def _observation(asset, frame, decision, model, multiplier, delay, costs):
    start = decision["position"] + 1 + delay
    future = frame.iloc[start : start + 20]
    entry = float(future.open.iloc[0])
    row = {
        "ticker": asset["ticker"],
        "market": asset["market"],
        "date": decision["date"],
        "label_end_date": decision["label_end_date"],
        "entry_date": future.index[0].date().isoformat(),
        "score": decision["score"],
        "champion_action": decision["champion_action"],
        "active": decision["active"][model],
    }
    if not row["active"]:
        return {
            **row,
            "status": "idle",
            "gross_return_pct": 0.0,
            "net_return_pct": 0.0,
            "cost_pct": 0.0,
        }
    target, stop = decision["target"], decision["stop"]
    if model != "buy_and_hold_sleeve" and not (stop < entry < target):
        return {**row, "status": "excluded", "reason": "entry_gap_outside_original_barriers"}
    terminal = (
        None if model == "buy_and_hold_sleeve" else evaluate_barriers("BUY", target, stop, future)
    )
    exit_price = float(future.close.iloc[-1])
    if terminal:
        hit = future.loc[pd.Timestamp(terminal[1])]
        exit_price = (
            min(float(stop), float(hit.open))
            if terminal[0] in {"hit_stop", "ambiguous"}
            else float(target)
        )
    gross = (exit_price / entry - 1) * 100
    # No inferred historical FX/liquidity: use the existing conservative unknown-liquidity cost.
    cost = (
        estimate_round_trip_cost_pct(
            action="BUY", market=asset["market"], average_trading_value=None, **costs
        )["total_cost_pct"]
        * multiplier
    )
    return {
        **row,
        "status": "evaluated",
        "outcome": terminal[0] if terminal else "expired",
        "gross_return_pct": round(gross, 6),
        "net_return_pct": round(gross - cost, 6),
        "cost_pct": round(cost, 6),
    }


def _summary(rows):
    cohorts = defaultdict(list)
    for row in rows:
        if row["status"] in {"evaluated", "idle"}:
            cohorts[row["date"]].append(row["net_return_pct"])
    values = [sum(items) / len(items) for items in cohorts.values()]
    return {
        "status": "available" if values else "unavailable",
        "cohort_count": len(values),
        "asset_observation_count": len(rows),
        "active_observation_count": sum(row["status"] == "evaluated" for row in rows),
        "excluded_count": sum(row["status"] == "excluded" for row in rows),
        "mean_cohort_net_return_pct": round(sum(values) / len(values), 6) if values else None,
    }


def _validation(decisions):
    # Purge the entire date cohort by its latest constituent label end.
    latest = {}
    for row in decisions:
        latest[row["date"]] = max(latest.get(row["date"], ""), row["label_end_date"])
    samples = [{"date": date, "label_end_date": end} for date, end in sorted(latest.items())]
    return samples, create_walk_forward_folds(samples, train_size=6, test_size=3, forward_days=1)


def _paired_summary(rows, champion):
    def usable(items):
        return {
            (row["date"], row["market"], row["ticker"]): row
            for row in items
            if row["status"] in {"evaluated", "idle"}
        }

    selected, baseline = usable(rows), usable(champion)
    cohorts = defaultdict(list)
    common = selected.keys() & baseline.keys()
    for key in sorted(common):
        cohorts[key[0]].append(selected[key]["net_return_pct"] - baseline[key]["net_return_pct"])
    deltas = [sum(values) / len(values) for values in cohorts.values()]
    return {
        "cohort_count": len(deltas),
        "paired_asset_count": len(common),
        "unpaired_usable_asset_count": len(selected.keys() ^ baseline.keys()),
        "mean_cohort_delta_pct": round(sum(deltas) / len(deltas), 6) if deltas else None,
    }


def run_challenger_research(payload: dict[str, Any]) -> dict[str, Any]:
    input_hash = _digest(payload)
    costs = payload["costs"]
    if set(costs) != {"fee_rate_pct", "kr_tax_rate_pct", "fx_spread_pct"} or any(
        not isfinite(float(value)) or float(value) < 0 for value in costs.values()
    ):
        raise ValueError("explicit_finite_nonnegative_costs_required")
    cutoff = pd.Timestamp(payload["as_of"], tz="UTC")
    if pd.isna(cutoff):
        raise ValueError("valid_as_of_required")
    hashes = _code_hashes()
    if any(hashes[name] != digest for name, digest in CHAMPION_SOURCES.items()):
        raise ValueError("champion_source_changed_requires_new_preregistration")
    prepared, unsupported = [], []
    seen = set()
    for asset in payload["assets"]:
        try:
            key = (asset.get("market"), asset.get("ticker"))
            if key in seen:
                raise ValueError("duplicate_asset")
            seen.add(key)
            frame = _frame(asset, cutoff)
            prepared.append((asset, frame, _decisions(asset, frame)))
        except (KeyError, ValueError, TypeError) as exc:
            unsupported.append({"ticker": asset.get("ticker"), "reason": str(exc)})
    samples, validation = _validation([row for _, _, decisions in prepared for row in decisions])
    folds = validation["folds"]
    test_dates = {samples[i]["date"] for fold in folds for i in fold["test_indices"]}
    experiments = []
    for model in CONFIG["hypotheses"]:
        for multiplier in CONFIG["cost_multipliers"]:
            for delay in CONFIG["extra_delay_sessions"]:
                observations = []
                for asset, frame, decisions in prepared:
                    for decision in decisions:
                        try:
                            observations.append(
                                _observation(
                                    asset, frame, decision, model, multiplier, delay, costs
                                )
                            )
                        except (KeyError, ValueError, TypeError) as exc:
                            observations.append(
                                {
                                    "date": decision["date"],
                                    "label_end_date": decision["label_end_date"],
                                    "ticker": asset["ticker"],
                                    "status": "excluded",
                                    "reason": str(exc),
                                }
                            )
                test = [row for row in observations if row["date"] in test_dates]
                experiments.append(
                    {
                        "model": model,
                        "cost_multiplier": multiplier,
                        "delay_sessions": delay,
                        "status": _summary(test)["status"],
                        "test": _summary(test),
                        "failures": dict(
                            Counter(
                                row["reason"] for row in observations if row["status"] == "excluded"
                            )
                        ),
                        "folds": [
                            {
                                "fold": fold["fold"],
                                "train_diagnostic": _summary(
                                    [
                                        row
                                        for row in observations
                                        if row["date"]
                                        in {samples[i]["date"] for i in fold["train_indices"]}
                                    ]
                                ),
                                "test": _summary(
                                    [
                                        row
                                        for row in observations
                                        if row["date"]
                                        in {samples[i]["date"] for i in fold["test_indices"]}
                                    ]
                                ),
                            }
                            for fold in folds
                        ],
                        "observations": observations,
                    }
                )
    for experiment in experiments:
        champion = next(
            row
            for row in experiments
            if row["model"] == "champion"
            and row["cost_multiplier"] == experiment["cost_multiplier"]
            and row["delay_sessions"] == experiment["delay_sessions"]
        )
        experiment["paired_test_vs_champion"] = _paired_summary(
            [row for row in experiment["observations"] if row["date"] in test_dates],
            [row for row in champion["observations"] if row["date"] in test_dates],
        )
    minimum_paired = min(row["paired_test_vs_champion"]["cohort_count"] for row in experiments)
    return {
        "research_only": True,
        "adoption_permitted": False,
        "return_basis": "price_return_after_estimated_costs",
        "conclusion": (
            "insufficient_evidence"
            if minimum_paired < 30 or len(folds) < 3
            else "descriptive_comparison_only"
        ),
        "config": deepcopy(CONFIG),
        "config_sha256": _digest(CONFIG),
        "input_sha256": input_hash,
        "code_sha256": hashes,
        "runtime": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
        },
        "price_provenance": deepcopy(payload.get("price_provenance", {})),
        "costs": costs,
        "as_of": cutoff.date().isoformat(),
        "folds": folds,
        "fold_unavailable_reason": validation["reason"],
        "unsupported_evidence": unsupported,
        "experiments": experiments,
        "limitations": [
            "Fixed hypotheses; train windows are diagnostics, not model fitting "
            "or independent future validation.",
            "Long-only independent sleeves; hysteresis is signal eligibility, "
            "not continuous position carry.",
            "Idle gaps are not a continuous equity curve; no compounding, "
            "annualization, or superiority claim.",
            "Cohorts equally weight supplied assets; exclusions can change membership "
            "across experiments. Paired deltas use only matched usable observations.",
            "Current supplied universe may contain survivorship bias; missing internal "
            "sessions lack calendar certification.",
            "OHLC barriers use conservative ambiguous-day stop and gap-stop pricing; "
            "no actual fills modeled.",
            "Price adjustment/currency consistency is caller-supplied evidence; "
            "unknown liquidity uses conservative cost.",
            "Price returns omit dividends/distributions and capital-gains tax; "
            "they are not total returns, especially for dividend ETFs.",
            "US sleeves assume round-trip FX conversion even when USD is already held; "
            "this is a conservative research cost assumption.",
        ],
    }
