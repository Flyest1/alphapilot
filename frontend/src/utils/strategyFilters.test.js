import { describe, expect, it } from "vitest";

import { filterStrategies, sortStrategies } from "./strategyFilters.js";

const strategies = [
  { ticker: "A", action: "BUY", reasoning: "기술 점수 80" },
  { ticker: "B", action: "SELL", reasoning: "기술 점수 30" },
  { ticker: "C", action: "WATCH", reasoning: "data-limited" },
];

describe("filterStrategies", () => {
  it("returns everything for ALL", () => {
    expect(filterStrategies(strategies, "ALL")).toHaveLength(3);
  });

  it("filters by action", () => {
    expect(filterStrategies(strategies, "BUY").map((row) => row.ticker)).toEqual(["A"]);
  });

  it("filters data-limited strategies regardless of action", () => {
    expect(filterStrategies(strategies, "DATA_LIMITED").map((row) => row.ticker)).toEqual(["C"]);
  });
});

describe("sortStrategies", () => {
  const unsorted = [
    { ticker: "A", action: "BUY", confidence: 60 },
    { ticker: "B", action: "BUY", confidence: 90 },
    { ticker: "C", action: "HOLD", confidence: 75 },
  ];
  const logs = [
    { ticker: "A", action: "BUY", return_after_20d: 8 },
    { ticker: "C", action: "HOLD", return_after_20d: -2 },
  ];

  it("keeps original order by default", () => {
    expect(sortStrategies(unsorted, "default", logs).map((row) => row.ticker)).toEqual([
      "A",
      "B",
      "C",
    ]);
  });

  it("sorts by confidence descending", () => {
    expect(sortStrategies(unsorted, "confidence", logs).map((row) => row.ticker)).toEqual([
      "B",
      "C",
      "A",
    ]);
  });

  it("sorts by the pre-calibration score so warnings do not invert rank", () => {
    const calibrated = [
      {
        ticker: "CALIBRATED",
        action: "BUY",
        confidence: 60,
        confidence_detail: {
          calibrated: true,
          base_confidence: 100,
          calibration_factor: 0.6,
        },
      },
      {
        ticker: "UNCALIBRATED",
        action: "BUY",
        confidence: 70,
        confidence_detail: { calibrated: false, base_confidence: 70 },
      },
    ];

    expect(sortStrategies(calibrated, "confidence").map((row) => row.ticker)).toEqual([
      "CALIBRATED",
      "UNCALIBRATED",
    ]);
  });

  it("falls back for legacy reports and pushes missing scores to the end", () => {
    const mixed = [
      { ticker: "MISSING", action: "WATCH" },
      { ticker: "LEGACY", action: "BUY", confidence: 80 },
      {
        ticker: "DETAIL",
        action: "BUY",
        confidence: 90,
        confidence_detail: { technical_confidence: 85 },
      },
    ];

    expect(sortStrategies(mixed, "confidence").map((row) => row.ticker)).toEqual([
      "DETAIL",
      "LEGACY",
      "MISSING",
    ]);
  });

  it("sorts by 20d return and pushes missing values to the end", () => {
    expect(sortStrategies(unsorted, "return20d", logs).map((row) => row.ticker)).toEqual([
      "A",
      "C",
      "B",
    ]);
  });
});
