"""Research-only paired cohort differences, never a win probability or promotion rule.

Input membership (including held-out folds) belongs to the caller. Eight comparisons,
30 dates, three-cohort circular blocks and the random seed are fixed method
parameters. This does not claim preregistration before historical data collection.
Percentile intervals use Bonferroni alpha=.05/8; they remain approximate bootstrap
intervals and cannot guarantee coverage or remove selection/survivorship bias.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from math import isfinite
from typing import Any

import numpy as np

COMPARISONS = 8
MIN_COHORTS = 30
BLOCK_LENGTH = 3
DRAWS = 2000
SEED = 20260911


def _eligible(rows: Sequence[Mapping[str, Any]]) -> tuple[dict, dict[str, int]]:
    indexed: dict = {}
    duplicates: set = set()
    excluded: dict[str, int] = defaultdict(int)
    for row in rows:
        status = row.get("status")
        if status not in {"evaluated", "idle"}:
            excluded[str(status) if status in {"excluded", "pending"} else "unknown_status"] += 1
            continue
        try:
            start = date.fromisoformat(str(row["date"]))
            end = date.fromisoformat(str(row["label_end_date"]))
            market, ticker = str(row["market"]).strip(), str(row["ticker"]).strip()
            value = float(row["net_return_pct"])
            if not market or not ticker or end < start or not isfinite(value):
                raise ValueError
            if status == "idle" and value != 0:
                raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError):
            excluded["invalid_observation"] += 1
            continue
        key = (start.isoformat(), market, ticker, end.isoformat())
        if key in indexed:
            duplicates.add(key)
            excluded["duplicate_key"] += 1
        indexed[key] = value
    for key in duplicates:
        del indexed[key]
        excluded["duplicate_key"] += 1
    return indexed, dict(sorted(excluded.items()))


def paired_research_statistics(
    model_observations: Sequence[Mapping[str, Any]],
    champion_observations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Pair exact identities, average within dates, then bootstrap ordered date blocks.

    net_return_pct is in percentage points, not a fraction. Evaluated and explicit
    zero-return idle decisions participate; excluded/pending/unknown records do not.
    Duplicate identities are ambiguous and removed entirely. A date with many
    stocks contributes one equal-weight cohort, just like a date with one stock.
    """
    model, model_exclusions = _eligible(model_observations)
    champion, champion_exclusions = _eligible(champion_observations)
    keys = sorted(model.keys() & champion.keys())
    by_date: dict[str, list[float]] = defaultdict(list)
    for key in keys:
        by_date[key[0]].append(model[key] - champion[key])
    values = np.array([np.mean(by_date[day]) for day in sorted(by_date)], dtype=float)
    count = len(values)
    result = {
        "status": "available" if count >= MIN_COHORTS else "insufficient_data",
        "paired_record_count": len(keys),
        "cohort_count": count,
        "eligible_model_count": len(model),
        "eligible_champion_count": len(champion),
        "model_pair_coverage": len(keys) / len(model) if model else None,
        "champion_pair_coverage": len(keys) / len(champion) if champion else None,
        "model_exclusions": model_exclusions,
        "champion_exclusions": champion_exclusions,
        "mean_difference_pct": float(np.mean(values)) if count else None,
        "interval_pct": None,
        "crosses_zero": None,
        "comparison_count": COMPARISONS,
        "family_alpha": 0.05,
        "interval_alpha": 0.05 / COMPARISONS,
        "method": "paired_date_circular_moving_block_percentile_bonferroni",
        "block_length": BLOCK_LENGTH,
        "draws": DRAWS,
        "seed": SEED,
        "research_only": True,
    }
    if count < MIN_COHORTS:
        return result
    random = np.random.default_rng(SEED)
    starts = random.integers(0, count, size=(DRAWS, (count + BLOCK_LENGTH - 1) // BLOCK_LENGTH))
    indices = (starts[:, :, None] + np.arange(BLOCK_LENGTH)) % count
    sampled = values[indices.reshape(DRAWS, -1)[:, :count]].mean(axis=1)
    tail = result["interval_alpha"] / 2
    lower, upper = np.quantile(sampled, [tail, 1 - tail])
    result["interval_pct"] = [float(lower), float(upper)]
    result["crosses_zero"] = bool(lower <= 0 <= upper)
    return result
