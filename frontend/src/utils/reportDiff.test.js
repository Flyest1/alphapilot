import { describe, expect, it } from "vitest";

import { diffReports, findPreviousReport } from "./reportDiff.js";

function makeReport(id, createdAt, strategies) {
  return {
    id,
    report_type: "domestic",
    created_at: createdAt,
    content: { asset_strategies: strategies },
  };
}

const previous = makeReport("r1", "2026-06-10T08:30:00+09:00", [
  { ticker: "005930", name: "삼성전자", action: "HOLD", confidence: 70 },
  { ticker: "035420", name: "NAVER", action: "BUY", confidence: 75 },
  { ticker: "REMOVED", name: "제외 종목", action: "WATCH", confidence: 60 },
]);

const current = makeReport("r2", "2026-06-11T08:30:00+09:00", [
  { ticker: "005930", name: "삼성전자", action: "REDUCE", confidence: 48 },
  { ticker: "035420", name: "NAVER", action: "BUY", confidence: 78 },
  { ticker: "NEW", name: "신규 종목", action: "BUY", confidence: 80 },
]);

describe("diffReports", () => {
  it("detects action changes, large confidence moves, and added/removed tickers", () => {
    const diff = diffReports(current, previous);

    expect(diff.hasChanges).toBe(true);
    expect(diff.actionChanges).toEqual([
      { ticker: "005930", name: "삼성전자", from: "HOLD", to: "REDUCE" },
    ]);
    expect(diff.confidenceChanges).toEqual([
      { ticker: "005930", name: "삼성전자", from: 70, to: 48, delta: -22 },
    ]);
    expect(diff.added.map((row) => row.ticker)).toEqual(["NEW"]);
    expect(diff.removed.map((row) => row.ticker)).toEqual(["REMOVED"]);
  });

  it("returns null without a previous report", () => {
    expect(diffReports(current, null)).toBeNull();
  });

  it("reports no changes for identical strategies", () => {
    const diff = diffReports(previous, previous);
    expect(diff.hasChanges).toBe(false);
  });
});

describe("findPreviousReport", () => {
  it("returns the next same-type report in the descending list", () => {
    const globalReport = { id: "g1", report_type: "global", created_at: "2026-06-10" };
    const reports = [current, globalReport, previous];

    expect(findPreviousReport(current, reports)?.id).toBe("r1");
    expect(findPreviousReport(previous, reports)).toBeNull();
    expect(findPreviousReport(null, reports)).toBeNull();
  });
});
