import { describe, expect, it } from "vitest";

import { findPerformanceLog, logsForReport } from "./performanceLogs.js";

const logs = [
  { id: "new", report_id: "r2", ticker: "AAPL", action: "BUY", return_after_20d: 5 },
  { id: "old", report_id: "r1", ticker: "AAPL", action: "BUY", return_after_20d: -3 },
  { id: "legacy", report_id: null, ticker: "MSFT", action: "HOLD" },
];

describe("performance log matching", () => {
  it("scopes logs to the selected report and keeps legacy rows", () => {
    expect(logsForReport(logs, "r1").map((row) => row.id)).toEqual(["old", "legacy"]);
    expect(logsForReport(logs, "").map((row) => row.id)).toEqual(["new", "old", "legacy"]);
  });

  it("returns the selected report's log instead of the newest ticker match", () => {
    const strategy = { ticker: "AAPL", action: "BUY" };
    expect(findPerformanceLog(strategy, logsForReport(logs, "r1"))?.id).toBe("old");
    expect(findPerformanceLog(strategy, logs)?.id).toBe("new");
    expect(findPerformanceLog({ ticker: "AAPL", action: "SELL" }, logs)).toBeUndefined();
  });
});
