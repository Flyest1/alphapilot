import { describe, expect, it } from "vitest";

import { filterStrategies } from "./strategyFilters.js";

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
