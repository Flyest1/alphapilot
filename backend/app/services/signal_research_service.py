"""Pure, research-only evaluation for candidate technical signals.

This module never changes production scores, recommendation actions, persisted data, or
report content.  It evaluates already-labelled observations and returns JSON-safe
diagnostics that a human can review before considering any later model change.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from math import ceil
from typing import Any

import numpy as np
import pandas as pd

from app.services.backtest_validation import create_walk_forward_folds

MINIMUM_SAMPLE_COUNT = 30
MINIMUM_COHORT_COUNT = 30
MINIMUM_MARKET_SAMPLE_COUNT = 20
MINIMUM_WALK_FORWARD_FOLDS = 3
MINIMUM_FOLD_SAMPLE_COUNT = 5
HIGH_CORRELATION_THRESHOLD = 0.8
DEFAULT_QUANTILE = 0.2

RESEARCH_DISCLAIMER = (
    "Research-only signal diagnostics. Results are historical, cost-deducted observations "
    "and are not investment advice, a production score, a recommendation, or a trade instruction."
)

ECONOMIC_HYPOTHESIS_REGISTRY: dict[str, dict[str, str]] = {
    "trend_strength": {
        "hypothesis": "Persistent directional demand may continue after a confirmed trend.",
        "economic_rationale": "Slow information diffusion and investor herding can sustain trends.",
    },
    "short_term_momentum": {
        "hypothesis": "Recent relative winners may retain short-horizon strength.",
        "economic_rationale": (
            "Under-reaction and gradual portfolio rebalancing can create momentum."
        ),
    },
    "volume_flow": {
        "hypothesis": "Price moves confirmed by participation may contain more information.",
        "economic_rationale": (
            "Informed trading and liquidity demand can appear in volume patterns."
        ),
    },
    "volatility_regime": {
        "hypothesis": "Return distributions differ across volatility regimes.",
        "economic_rationale": "Risk appetite and uncertainty alter expected compensation for risk.",
    },
    "relative_strength": {
        "hypothesis": "Assets outperforming their comparable market may retain relative demand.",
        "economic_rationale": "Capital reallocations can be gradual across sectors and assets.",
    },
    "event_theme": {
        "hypothesis": "Fundamental events can change expectations before prices fully adjust.",
        "economic_rationale": "Information processing and estimate revisions can be delayed.",
    },
}


class SignalResearchService:
    """Evaluate candidate signals without fitting or changing an operating model."""

    def evaluate(
        self,
        samples: Iterable[Mapping[str, Any]] | pd.DataFrame,
        *,
        quantile: float = DEFAULT_QUANTILE,
        walk_forward_folds: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Return deterministic, JSON-serializable diagnostics for each supplied signal.

        Every observation must include ``date``, ``label_end_date``, ``ticker``, ``market``,
        ``regime``, ``technical_score``, ``net_return_pct``, and a mapping in ``signals``.
        Rankings are calculated within each decision date solely from contemporaneous signal
        values. The forward ``net_return_pct`` label is never used to construct a rank or a
        selection.
        """

        if not 0 < quantile <= 0.5:
            raise ValueError("quantile must be greater than 0 and no greater than 0.5")

        frame, signal_names = self._samples_frame(samples)
        folds = self._resolve_folds(frame, walk_forward_folds)
        signal_correlations = self._signal_correlations(frame, signal_names)
        analyses = [
            self._evaluate_signal(
                frame,
                signal_name,
                quantile=quantile,
                folds=folds,
                signal_correlations=signal_correlations,
            )
            for signal_name in signal_names
        ]
        return {
            "research_only": True,
            "disclaimer": RESEARCH_DISCLAIMER,
            "adoption_permitted": False,
            "adoption_note": (
                "This service cannot adopt signals. Any production-score change requires separate "
                "approval after independent review."
            ),
            "minimum_requirements": {
                "total_samples": MINIMUM_SAMPLE_COUNT,
                "non_overlapping_cohorts": MINIMUM_COHORT_COUNT,
                "samples_per_market": MINIMUM_MARKET_SAMPLE_COUNT,
                "walk_forward_folds": MINIMUM_WALK_FORWARD_FOLDS,
                "minimum_fold_samples": MINIMUM_FOLD_SAMPLE_COUNT,
                "high_correlation_absolute_threshold": HIGH_CORRELATION_THRESHOLD,
            },
            "leakage_safeguards": [
                "Ranks and selections use only same-date technical and signal values.",
                "Forward net_return_pct is used only after selections are fixed for evaluation.",
                "Walk-forward summaries use disjoint chronological test-date folds.",
            ],
            "statistical_caveats": [
                "Candidate status is exploratory and does not include multiple-testing correction.",
                "Cross-sectional ties at a selection boundary are retained together.",
            ],
            "sample_count": int(len(frame)),
            "cohort_count": self._non_overlapping_cohort_count(frame),
            "signal_count": len(signal_names),
            "economic_hypotheses": {
                signal_name: self._hypothesis_for(signal_name) for signal_name in signal_names
            },
            "walk_forward": {
                "fold_count": len(folds),
                "valid_fold_count": sum(
                    fold["sample_count"] >= MINIMUM_FOLD_SAMPLE_COUNT for fold in folds
                ),
                "folds": [self._fold_metadata(fold) for fold in folds],
            },
            "signals": analyses,
        }

    def _samples_frame(
        self,
        samples: Iterable[Mapping[str, Any]] | pd.DataFrame,
    ) -> tuple[pd.DataFrame, list[str]]:
        rows = samples.to_dict("records") if isinstance(samples, pd.DataFrame) else list(samples)
        required = {
            "date",
            "label_end_date",
            "ticker",
            "market",
            "regime",
            "technical_score",
            "net_return_pct",
            "signals",
        }
        for row in rows:
            missing = required.difference(row)
            if missing:
                raise ValueError(
                    f"Signal research sample missing required fields: {sorted(missing)}"
                )
            if not isinstance(row["signals"], Mapping):
                raise ValueError("Signal research sample signals must be a mapping")

        signal_names = sorted({str(name) for row in rows for name in row["signals"]})
        columns = [
            "_input_position",
            "date",
            "label_end_date",
            "ticker",
            "market",
            "regime",
            "technical_score",
            "net_return_pct",
            *signal_names,
        ]
        if not rows:
            return pd.DataFrame(columns=columns), signal_names

        normalized_rows = []
        for input_position, row in enumerate(rows):
            normalized = {
                "_input_position": input_position,
                "date": row["date"],
                "label_end_date": row["label_end_date"],
                "ticker": str(row["ticker"]),
                "market": str(row["market"]),
                "regime": str(row["regime"]),
                "technical_score": row["technical_score"],
                "net_return_pct": row["net_return_pct"],
            }
            normalized.update({name: row["signals"].get(name) for name in signal_names})
            normalized_rows.append(normalized)

        frame = pd.DataFrame(normalized_rows, columns=columns)
        frame["date"] = pd.to_datetime(frame["date"], errors="raise", utc=True).dt.tz_localize(None)
        frame["label_end_date"] = pd.to_datetime(
            frame["label_end_date"], errors="raise", utc=True
        ).dt.tz_localize(None)
        if (frame["label_end_date"] < frame["date"]).any():
            raise ValueError("Signal research label_end_date must not precede date")
        for column in ("technical_score", "net_return_pct", *signal_names):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if not np.isfinite(frame["technical_score"]).all():
            raise ValueError("Signal research sample contains non-finite technical_score")
        if not np.isfinite(frame["net_return_pct"]).all():
            raise ValueError("Signal research sample contains non-finite net_return_pct")
        return (
            frame.sort_values(["date", "ticker"], kind="stable").reset_index(drop=True),
            signal_names,
        )

    def _resolve_folds(
        self,
        frame: pd.DataFrame,
        supplied_folds: Sequence[Mapping[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if frame.empty:
            return []
        if supplied_folds is None:
            dates = list(frame["date"].drop_duplicates())
            validation = create_walk_forward_folds(
                frame.to_dict("records"),
                train_size=max(10, len(dates) * 2 // 5),
                test_size=max(5, len(dates) // 6),
                forward_days=1,
            )
            return [
                self._make_fold(index, frame.iloc[fold["test_indices"]])
                for index, fold in enumerate(validation["folds"])
            ]

        folds = []
        seen_test_dates: set[pd.Timestamp] = set()
        previous_end: pd.Timestamp | None = None
        for index, supplied_fold in enumerate(supplied_folds):
            if "test_indices" in supplied_fold:
                positions = list(supplied_fold["test_indices"])
                if any(not isinstance(position, (int, np.integer)) for position in positions):
                    raise ValueError("walk-forward test_indices must contain integers")
                if any(position < 0 or position >= len(frame) for position in positions):
                    raise ValueError("walk-forward test_indices contain an invalid sample position")
                if len(positions) != len(set(positions)):
                    raise ValueError("walk-forward test_indices must not contain duplicates")
                fold_frame = frame[frame["_input_position"].isin(positions)]
            elif "test_dates" in supplied_fold:
                test_dates = pd.to_datetime(
                    list(supplied_fold["test_dates"]), errors="raise", utc=True
                )
                fold_frame = frame[frame["date"].isin(test_dates.tz_localize(None))]
            else:
                raise ValueError("walk-forward folds require test_indices or test_dates")
            fold_dates = set(fold_frame["date"].drop_duplicates())
            if fold_dates.intersection(seen_test_dates):
                raise ValueError("walk-forward test dates must not overlap")
            if fold_dates:
                fold_start = min(fold_dates)
                if previous_end is not None and fold_start <= previous_end:
                    raise ValueError("walk-forward folds must be chronological")
                previous_end = max(fold_dates)
                seen_test_dates.update(fold_dates)
            folds.append(self._make_fold(index, fold_frame))
        return folds

    def _make_fold(self, index: int, frame: pd.DataFrame) -> dict[str, Any]:
        return {
            "fold": index,
            "frame": frame.copy(),
            "sample_count": int(len(frame)),
            "start_date": self._date_or_none(frame, first=True),
            "end_date": self._date_or_none(frame, first=False),
        }

    def _evaluate_signal(
        self,
        frame: pd.DataFrame,
        signal_name: str,
        *,
        quantile: float,
        folds: Sequence[Mapping[str, Any]],
        signal_correlations: Mapping[tuple[str, str], float | None],
    ) -> dict[str, Any]:
        usable = frame[
            [
                "date",
                "label_end_date",
                "ticker",
                "market",
                "regime",
                "technical_score",
                "net_return_pct",
                signal_name,
            ]
        ].dropna()
        signal_values = usable[signal_name]
        total_count = int(len(usable))
        cohort_count = self._non_overlapping_cohort_count(usable)
        signal_return_spearman = self._cross_sectional_spearman(
            usable, signal_name, "net_return_pct"
        )
        technical_score_spearman = self._cross_sectional_spearman(
            usable, signal_name, "technical_score"
        )
        redundant_with = [
            other_name
            for other_name in sorted(
                {pair[1] for pair in signal_correlations if pair[0] == signal_name}
            )
            if self._is_high_correlation(signal_correlations[(signal_name, other_name)])
        ]
        fold_results = [self._fold_signal_result(fold, signal_name, quantile) for fold in folds]
        valid_fold_results = [
            result for result in fold_results if result["sample_count"] >= MINIMUM_FOLD_SAMPLE_COUNT
        ]
        standalone = self._selection_metrics(usable, signal_name, quantile)
        incremental = self._incremental_metrics(usable, signal_name, quantile)
        market_summary = self._group_summary(usable, signal_name, "market", quantile)
        regime_summary = self._group_summary(usable, signal_name, "regime", quantile)
        status, reasons = self._status(
            total_count=total_count,
            cohort_count=cohort_count,
            signal_values=signal_values,
            technical_score_spearman=technical_score_spearman,
            redundant_with=redundant_with,
            valid_fold_results=valid_fold_results,
            standalone=standalone,
            incremental=incremental,
            market_summary=market_summary,
            regime_summary=regime_summary,
        )
        return {
            "signal": signal_name,
            "status": status,
            "reasons": reasons,
            "sample_count": total_count,
            "economic_hypothesis": self._hypothesis_for(signal_name),
            "spearman": {
                "signal_to_net_return": self._rounded(signal_return_spearman),
                "signal_to_technical_score": self._rounded(technical_score_spearman),
            },
            "redundancy": {
                "high_correlation_threshold": HIGH_CORRELATION_THRESHOLD,
                "highly_correlated_signals": redundant_with,
                "signal_correlations": self._signal_correlation_rows(
                    signal_name, signal_correlations
                ),
            },
            "standalone_spread": standalone,
            "incremental_rank_combination": incremental,
            "consistency": {
                "by_market": market_summary,
                "by_regime": regime_summary,
                "walk_forward_folds": fold_results,
                "walk_forward_direction": self._direction_summary(valid_fold_results),
            },
        }

    def _status(
        self,
        *,
        total_count: int,
        cohort_count: int,
        signal_values: pd.Series,
        technical_score_spearman: float | None,
        redundant_with: list[str],
        valid_fold_results: Sequence[Mapping[str, Any]],
        standalone: Mapping[str, Any],
        incremental: Mapping[str, Any],
        market_summary: Sequence[Mapping[str, Any]],
        regime_summary: Sequence[Mapping[str, Any]],
    ) -> tuple[str, list[str]]:
        reasons = []
        if total_count == 0:
            reasons.append("no_finite_signal_values")
        elif signal_values.nunique(dropna=True) < 2:
            reasons.append("constant_signal")
        if total_count < MINIMUM_SAMPLE_COUNT:
            reasons.append(f"insufficient_samples:{total_count}/{MINIMUM_SAMPLE_COUNT}")
        if cohort_count < MINIMUM_COHORT_COUNT:
            reasons.append(f"insufficient_cohorts:{cohort_count}/{MINIMUM_COHORT_COUNT}")
        if len(valid_fold_results) < MINIMUM_WALK_FORWARD_FOLDS:
            reasons.append(
                "insufficient_walk_forward_folds:"
                f"{len(valid_fold_results)}/{MINIMUM_WALK_FORWARD_FOLDS}"
            )
        if self._is_high_correlation(technical_score_spearman):
            reasons.append("high_correlation_with_technical_score")
        if redundant_with:
            reasons.append("high_correlation_with_signals:" + ",".join(redundant_with))
        if not self._is_positive(standalone.get("net_return_spread_pct")):
            reasons.append("non_positive_standalone_spread")
        incremental_result = incremental.get("incremental", {})
        if not self._is_positive(incremental_result.get("expected_value_pct")):
            reasons.append("non_positive_incremental_expected_value")
        if self._is_positive(incremental_result.get("turnover_proxy")):
            reasons.append("turnover_worsened")
        baseline_drawdown = incremental.get("baseline_technical_score", {}).get("max_drawdown_pct")
        combined_drawdown = incremental.get("combined_rank", {}).get("max_drawdown_pct")
        if (
            baseline_drawdown is not None
            and combined_drawdown is not None
            and float(combined_drawdown) < float(baseline_drawdown)
        ):
            reasons.append("max_drawdown_worsened")
        direction = self._direction_summary(valid_fold_results)
        if not direction["consistent"] or direction["direction"] != "positive":
            reasons.append("inconsistent_walk_forward_direction")
        if not market_summary or not self._all_positive_groups(market_summary):
            reasons.append("insufficient_market_consistency")
        if any(
            int(group["sample_count"]) < MINIMUM_MARKET_SAMPLE_COUNT for group in market_summary
        ):
            reasons.append("insufficient_market_samples")
        if len(regime_summary) < 2 or not self._all_positive_groups(regime_summary):
            reasons.append("insufficient_regime_consistency")
        return ("rejected", reasons) if reasons else ("candidate", [])

    def _selection_metrics(
        self,
        frame: pd.DataFrame,
        ranking_column: str,
        quantile: float,
    ) -> dict[str, Any]:
        if frame.empty or frame[ranking_column].nunique() < 2:
            return self._empty_spread()
        selected = self._select_by_date(frame, ranking_column, quantile)
        return {
            "quantile": quantile,
            "sample_count": int(len(frame)),
            "top_sample_count": int(len(selected["top"])),
            "bottom_sample_count": int(len(selected["bottom"])),
            "top_net_return_pct": self._mean(selected["top"]["net_return_pct"]),
            "bottom_net_return_pct": self._mean(selected["bottom"]["net_return_pct"]),
            "net_return_spread_pct": self._difference(
                selected["top"]["net_return_pct"], selected["bottom"]["net_return_pct"]
            ),
        }

    def _incremental_metrics(
        self,
        frame: pd.DataFrame,
        signal_name: str,
        quantile: float,
    ) -> dict[str, Any]:
        if frame.empty or frame[signal_name].nunique() < 2:
            return self._empty_incremental()
        baseline = self._select_by_date(frame, "technical_score", quantile)["top"]
        combined = self._select_combined_by_date(frame, signal_name, quantile)
        baseline_metrics = self._portfolio_proxy_metrics(baseline)
        combined_metrics = self._portfolio_proxy_metrics(combined)
        return {
            "quantile": quantile,
            "baseline_technical_score": baseline_metrics,
            "combined_rank": combined_metrics,
            "incremental": {
                "expected_value_pct": self._subtract(
                    combined_metrics["expected_value_pct"], baseline_metrics["expected_value_pct"]
                ),
                "hit_rate": self._subtract(
                    combined_metrics["hit_rate"], baseline_metrics["hit_rate"]
                ),
                "turnover_proxy": self._subtract(
                    combined_metrics["turnover_proxy"], baseline_metrics["turnover_proxy"]
                ),
            },
        }

    def _select_by_date(
        self,
        frame: pd.DataFrame,
        ranking_column: str,
        quantile: float,
    ) -> dict[str, pd.DataFrame]:
        top_rows = []
        bottom_rows = []
        for _, date_frame in frame.groupby("date", sort=True):
            select_count = max(1, ceil(len(date_frame) * quantile))
            top_threshold = date_frame[ranking_column].nlargest(select_count).iloc[-1]
            bottom_threshold = date_frame[ranking_column].nsmallest(select_count).iloc[-1]
            top_rows.append(date_frame[date_frame[ranking_column] >= top_threshold])
            bottom_rows.append(date_frame[date_frame[ranking_column] <= bottom_threshold])
        return {"top": pd.concat(top_rows), "bottom": pd.concat(bottom_rows)}

    def _select_combined_by_date(
        self,
        frame: pd.DataFrame,
        signal_name: str,
        quantile: float,
    ) -> pd.DataFrame:
        selections = []
        for _, date_frame in frame.groupby("date", sort=True):
            ranked = date_frame.copy()
            ranked["combined_rank"] = (
                ranked["technical_score"].rank(method="average", pct=True)
                + ranked[signal_name].rank(method="average", pct=True)
            ) / 2
            select_count = max(1, ceil(len(ranked) * quantile))
            threshold = ranked["combined_rank"].nlargest(select_count).iloc[-1]
            selections.append(ranked[ranked["combined_rank"] >= threshold])
        return pd.concat(selections)

    def _portfolio_proxy_metrics(self, selected: pd.DataFrame) -> dict[str, float | int | None]:
        if selected.empty:
            return {
                "sample_count": 0,
                "expected_value_pct": None,
                "hit_rate": None,
                "turnover_proxy": None,
                "max_drawdown_pct": None,
            }
        date_sets = [
            set(date_frame["ticker"]) for _, date_frame in selected.groupby("date", sort=True)
        ]
        turnover = []
        for previous, current in zip(date_sets, date_sets[1:]):
            denominator = max(len(previous), len(current), 1)
            turnover.append(len(previous.symmetric_difference(current)) / (2 * denominator))
        daily_returns = selected.groupby("date", sort=True)["net_return_pct"].mean() / 100
        equity = (1 + daily_returns).cumprod()
        drawdown = (equity / equity.cummax() - 1) * 100
        return {
            "sample_count": int(len(selected)),
            "expected_value_pct": self._mean(selected["net_return_pct"]),
            "hit_rate": self._rounded(float((selected["net_return_pct"] > 0).mean())),
            "turnover_proxy": self._rounded(float(np.mean(turnover))) if turnover else 0.0,
            "max_drawdown_pct": self._rounded(float(drawdown.min())),
        }

    def _group_summary(
        self,
        frame: pd.DataFrame,
        signal_name: str,
        group_column: str,
        quantile: float,
    ) -> list[dict[str, Any]]:
        summaries = []
        for group, group_frame in frame.groupby(group_column, sort=True):
            spread = self._selection_metrics(group_frame, signal_name, quantile)
            summaries.append(
                {
                    group_column: str(group),
                    "sample_count": int(len(group_frame)),
                    "net_return_spread_pct": spread["net_return_spread_pct"],
                    "direction": self._direction(spread["net_return_spread_pct"]),
                }
            )
        return summaries

    def _fold_signal_result(
        self,
        fold: Mapping[str, Any],
        signal_name: str,
        quantile: float,
    ) -> dict[str, Any]:
        fold_frame = fold["frame"]
        usable = fold_frame.dropna(subset=[signal_name])
        spread = self._selection_metrics(usable, signal_name, quantile)
        incremental = self._incremental_metrics(usable, signal_name, quantile)
        return {
            **self._fold_metadata(fold),
            "sample_count": int(len(usable)),
            "net_return_spread_pct": spread["net_return_spread_pct"],
            "incremental_expected_value_pct": incremental["incremental"]["expected_value_pct"],
            "direction": self._direction(spread["net_return_spread_pct"]),
        }

    def _direction_summary(self, fold_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        directions = [
            result["direction"]
            for result in fold_results
            if result["direction"] != "flat_or_unknown"
        ]
        return {
            "valid_fold_count": len(fold_results),
            "positive_fold_count": directions.count("positive"),
            "negative_fold_count": directions.count("negative"),
            "consistent": len(directions) >= MINIMUM_WALK_FORWARD_FOLDS
            and len(set(directions)) == 1,
            "direction": (
                directions[0] if directions and len(set(directions)) == 1 else "mixed_or_unknown"
            ),
        }

    def _signal_correlations(
        self,
        frame: pd.DataFrame,
        signal_names: Sequence[str],
    ) -> dict[tuple[str, str], float | None]:
        correlations: dict[tuple[str, str], float | None] = {}
        for index, first in enumerate(signal_names):
            for second in signal_names[index + 1 :]:
                correlations[(first, second)] = self._cross_sectional_spearman(frame, first, second)
                correlations[(second, first)] = correlations[(first, second)]
        return correlations

    def _signal_correlation_rows(
        self,
        signal_name: str,
        correlations: Mapping[tuple[str, str], float | None],
    ) -> list[dict[str, Any]]:
        return [
            {
                "signal": other_name,
                "spearman": self._rounded(correlations[(signal_name, other_name)]),
                "high_correlation": self._is_high_correlation(
                    correlations[(signal_name, other_name)]
                ),
            }
            for other_name in sorted({pair[1] for pair in correlations if pair[0] == signal_name})
        ]

    def _hypothesis_for(self, signal_name: str) -> dict[str, str]:
        category = signal_name
        if signal_name.startswith("sma_"):
            category = "trend_strength"
        elif signal_name.startswith("return_") or signal_name == "momentum_consistency":
            category = "short_term_momentum"
        elif "volume" in signal_name or "traded_value" in signal_name:
            category = "volume_flow"
        elif (
            "volatility" in signal_name
            or "atr_percentile" in signal_name
            or "drawdown" in signal_name
        ):
            category = "volatility_regime"
        elif signal_name.startswith("relative_strength"):
            category = "relative_strength"
        return ECONOMIC_HYPOTHESIS_REGISTRY.get(
            category,
            {
                "hypothesis": (
                    "Candidate signal requires a documented economic hypothesis before review."
                ),
                "economic_rationale": (
                    "No registered rationale; historical association alone is insufficient."
                ),
            },
        )

    def _fold_metadata(self, fold: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "fold": int(fold["fold"]),
            "sample_count": int(fold["sample_count"]),
            "start_date": fold["start_date"],
            "end_date": fold["end_date"],
        }

    @staticmethod
    def _spearman(first: pd.Series, second: pd.Series) -> float | None:
        paired = pd.concat([first, second], axis=1).dropna()
        if len(paired) < 2 or paired.iloc[:, 0].nunique() < 2 or paired.iloc[:, 1].nunique() < 2:
            return None
        value = paired.iloc[:, 0].corr(paired.iloc[:, 1], method="spearman")
        return float(value) if pd.notna(value) and np.isfinite(value) else None

    def _cross_sectional_spearman(
        self,
        frame: pd.DataFrame,
        first_column: str,
        second_column: str,
    ) -> float | None:
        values = [
            self._spearman(date_frame[first_column], date_frame[second_column])
            for _, date_frame in frame.groupby("date", sort=True)
        ]
        finite = [value for value in values if value is not None]
        return self._rounded(float(np.mean(finite))) if finite else None

    @staticmethod
    def _non_overlapping_cohort_count(frame: pd.DataFrame) -> int:
        if frame.empty:
            return 0
        periods = (
            frame.groupby("date", sort=True)["label_end_date"]
            .max()
            .reset_index()
            .sort_values("date")
        )
        count = 0
        previous_end: pd.Timestamp | None = None
        for row in periods.itertuples(index=False):
            if previous_end is None or row.date > previous_end:
                count += 1
                previous_end = row.label_end_date
        return count

    @staticmethod
    def _date_or_none(frame: pd.DataFrame, *, first: bool) -> str | None:
        if frame.empty:
            return None
        date = frame["date"].min() if first else frame["date"].max()
        return pd.Timestamp(date).date().isoformat()

    @staticmethod
    def _is_high_correlation(value: float | None) -> bool:
        return value is not None and abs(value) >= HIGH_CORRELATION_THRESHOLD

    @staticmethod
    def _is_positive(value: Any) -> bool:
        return value is not None and float(value) > 0

    @staticmethod
    def _all_positive_groups(groups: Sequence[Mapping[str, Any]]) -> bool:
        return all(group.get("direction") == "positive" for group in groups)

    @staticmethod
    def _mean(values: pd.Series) -> float | None:
        return SignalResearchService._rounded(float(values.mean())) if len(values) else None

    @staticmethod
    def _difference(first: pd.Series, second: pd.Series) -> float | None:
        if not len(first) or not len(second):
            return None
        return SignalResearchService._rounded(float(first.mean() - second.mean()))

    @staticmethod
    def _subtract(first: float | None, second: float | None) -> float | None:
        return (
            SignalResearchService._rounded(first - second)
            if first is not None and second is not None
            else None
        )

    @staticmethod
    def _direction(value: float | None) -> str:
        if value is None or value == 0:
            return "flat_or_unknown"
        return "positive" if value > 0 else "negative"

    @staticmethod
    def _rounded(value: float | None) -> float | None:
        return round(value, 6) if value is not None and np.isfinite(value) else None

    @staticmethod
    def _empty_spread() -> dict[str, Any]:
        return {
            "quantile": DEFAULT_QUANTILE,
            "sample_count": 0,
            "top_sample_count": 0,
            "bottom_sample_count": 0,
            "top_net_return_pct": None,
            "bottom_net_return_pct": None,
            "net_return_spread_pct": None,
        }

    @staticmethod
    def _empty_incremental() -> dict[str, Any]:
        empty_metrics = {
            "sample_count": 0,
            "expected_value_pct": None,
            "hit_rate": None,
            "turnover_proxy": None,
            "max_drawdown_pct": None,
        }
        return {
            "quantile": DEFAULT_QUANTILE,
            "baseline_technical_score": empty_metrics.copy(),
            "combined_rank": empty_metrics.copy(),
            "incremental": {
                "expected_value_pct": None,
                "hit_rate": None,
                "turnover_proxy": None,
            },
        }


def evaluate_signal_research(
    samples: Iterable[Mapping[str, Any]] | pd.DataFrame,
    *,
    quantile: float = DEFAULT_QUANTILE,
    walk_forward_folds: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Convenience wrapper for pure research-signal evaluation."""

    return SignalResearchService().evaluate(
        samples,
        quantile=quantile,
        walk_forward_folds=walk_forward_folds,
    )
