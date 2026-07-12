import { describe, expect, it } from "vitest";

import {
  backtestSummary,
  baselineRows,
  costRows,
  metricValue,
  marketRows,
  regimeRows,
  signalResearchRows,
  walkForwardRows,
} from "./backtestResults.js";

const result = {
  metrics: {
    gross: { cumulative_return_pct: 12 },
    net: { cumulative_return_pct: 8, max_drawdown_pct: -4, sharpe: 1.2, expectancy_pct: 1 },
    excess_return_pct: 3,
  },
  costs: { fee_pct: 0.03, total_cost_pct: 0.8 },
  baselines: [
    {
      name: "buy_and_hold",
      label: "단순 보유",
      metrics: { gross: { cumulative_return_pct: 6 }, net: { cumulative_return_pct: 5 } },
    },
  ],
  regime_groups: [
    { regime: "bear", sample_count: 2, avg_net_return_pct: -1 },
    { regime: "bull", sample_count: 5, avg_net_return_pct: 2 },
  ],
  walk_forward: {
    folds: [
      {
        fold: 0,
        train_count: 10,
        test_count: 5,
        test_start_date: "2026-01-01",
        test_end_date: "2026-02-01",
        metrics: { net: { cumulative_return_pct: 2, max_drawdown_pct: -1 } },
      },
    ],
  },
  market_results: [
    {
      market: "US",
      sample_count: 10,
      metrics: { net: { cumulative_return_pct: 4, max_drawdown_pct: -2, sharpe: 1 } },
      baselines: [{ name: "buy_and_hold", metrics: { net: { cumulative_return_pct: 2 } } }],
      walk_forward: { fold_count: 2 },
    },
  ],
  signal_research: {
    research_only: true,
    adoption_permitted: false,
    signals: [
      {
        signal: "relative_strength_20",
        status: "candidate",
        sample_count: 30,
        reasons: [],
        standalone_spread: { net_return_spread_pct: 1.5 },
        incremental_rank_combination: { incremental: { expected_value_pct: 0.4 } },
        spearman: { signal_to_technical_score: 0.2 },
        consistency: { walk_forward_direction: { valid_fold_count: 3 } },
      },
    ],
  },
};

describe("backtestResults", () => {
  it("formats missing and finite metric values safely", () => {
    expect(metricValue(null)).toBe("-");
    expect(metricValue(1.234, 2, "%")).toBe("1.23%");
  });

  it("builds summary cards without requiring every metric", () => {
    const summary = backtestSummary(result);
    expect(summary.find((row) => row.label === "비용 후 누적").value).toBe("8.00%");
    expect(summary.find((row) => row.label === "Sortino").value).toBe("-");
  });

  it("normalizes baseline, regime, fold, and cost rows", () => {
    expect(baselineRows(result)[0]).toMatchObject({ name: "단순 보유", net: 5 });
    expect(regimeRows(result).map((row) => row.label)).toEqual(["상승장", "하락장"]);
    expect(walkForwardRows(result)[0]).toMatchObject({ fold: 1, testCount: 5, netReturn: 2 });
    expect(costRows(result).at(-1)).toEqual({ label: "평균 총비용", value: 0.8 });
    expect(marketRows(result)[0]).toMatchObject({
      market: "US",
      sampleCount: 10,
      foldCount: 2,
      benchmarkReturn: 2,
      excessReturn: 2,
    });
    expect(signalResearchRows(result)[0]).toMatchObject({
      signal: "relative_strength_20",
      statusLabel: "검토 후보",
      spread: 1.5,
      incrementalValue: 0.4,
      validFoldCount: 3,
    });
  });

  it("supports legacy backtest responses", () => {
    expect(backtestSummary({}).every((row) => row.value === "-")).toBe(true);
    expect(baselineRows({})).toEqual([]);
    expect(walkForwardRows({})).toEqual([]);
    expect(signalResearchRows({})).toEqual([]);
    expect(
      signalResearchRows({
        signal_research: { research_only: true, adoption_permitted: true, signals: [{}] },
      }),
    ).toEqual([]);
  });
});
