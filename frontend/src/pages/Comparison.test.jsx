import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  portfolio: { benchmarkReturns: vi.fn() },
}));

vi.mock("../api/client.js", () => ({
  api,
  isApiCacheFresh: vi.fn(() => false),
  readApiCache: vi.fn(() => null),
}));

import Comparison, { alignComparisonSeries } from "./Comparison.jsx";

describe("alignComparisonSeries", () => {
  it("uses the first observed date shared by every selected series and rebases to zero", () => {
    const result = alignComparisonSeries([
      {
        key: "kospi",
        points: [
          { date: "2026-08-03", return_rate: 5 },
          { date: "2026-08-01", return_rate: 1 },
          { date: "2026-08-02", return_rate: 3 },
        ],
      },
      {
        key: "alphapilot",
        points: [
          { date: "2026-08-02", return_rate: 10 },
          { date: "2026-08-03", return_rate: 21 },
        ],
      },
      {
        key: "actual_portfolio",
        points: [
          { date: "2026-08-02", return_rate: -5 },
          { date: "2026-08-03", return_rate: 4.5 },
        ],
      },
    ]);

    expect(result.commonStartDate).toBe("2026-08-02");
    expect(result.chartData[0]).toEqual({
      date: "2026-08-02",
      kospi: 0,
      alphapilot: 0,
      actual_portfolio: 0,
    });
    expect(result.chartData[1].kospi).toBeCloseTo(1.9417, 4);
    expect(result.chartData[1].alphapilot).toBeCloseTo(10, 4);
    expect(result.chartData[1].actual_portfolio).toBeCloseTo(10, 4);
  });

  it("does not invent a baseline when the selected series have no common observed date", () => {
    const result = alignComparisonSeries([
      { key: "kospi", points: [{ date: "2026-08-01", return_rate: 1 }] },
      { key: "alphapilot", points: [{ date: "2026-08-02", return_rate: 2 }] },
    ]);

    expect(result.commonStartDate).toBeNull();
    expect(result.chartData).toEqual([]);
    expect(result.series).toEqual([]);
  });

  it("ignores missing return values instead of treating them as zero", () => {
    const result = alignComparisonSeries([
      {
        key: "kospi",
        points: [
          { date: "2026-08-01", return_rate: null },
          { date: "2026-08-02", return_rate: 2 },
          { date: "2026-08-03", return_rate: 4.04 },
        ],
      },
      {
        key: "alphapilot",
        points: [
          { date: "2026-08-01", return_rate: 1 },
          { date: "2026-08-02", return_rate: 10 },
          { date: "2026-08-03", return_rate: 21 },
        ],
      },
    ]);

    expect(result.commonStartDate).toBe("2026-08-02");
    expect(result.chartData[0]).toEqual({ date: "2026-08-02", kospi: 0, alphapilot: 0 });
    expect(result.chartData[1].kospi).toBeCloseTo(2, 4);
    expect(result.chartData[1].alphapilot).toBeCloseTo(10, 4);
  });
});

describe("Comparison page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.portfolio.benchmarkReturns.mockResolvedValue({ series: [] });
  });

  it("loads the ten-day comparison range by default", async () => {
    render(<Comparison />);

    await waitFor(() => expect(api.portfolio.benchmarkReturns).toHaveBeenCalledWith(10));
    expect(screen.getByRole("button", { name: "10일" })).toHaveClass("active");
  });
});
