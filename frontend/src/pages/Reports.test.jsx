import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  reports: { latest: vi.fn(), list: vi.fn(), get: vi.fn() },
  assets: { list: vi.fn() },
  settings: { get: vi.fn() },
  performanceLogs: { list: vi.fn() },
  recommendationCycles: { list: vi.fn() },
}));

vi.mock("../api/client.js", () => ({
  api,
  isApiCacheFresh: () => false,
  readApiCache: () => null,
}));

import Reports from "./Reports.jsx";

function report(id, createdAt) {
  return {
    id,
    report_type: "domestic",
    title: "검증 리포트",
    created_at: createdAt,
    report_inputs: { ai_generation: { mode: "ai_narrative" } },
    content: {
      market_summary: { summary: "검증용 시장 요약", macro_factors: [], key_indices: [] },
      portfolio_summary: { risk_level: "medium" },
      key_risks: [],
      opportunities: [],
      asset_strategies: [
        { ticker: "005930", name: "검증 종목", action: "HOLD", confidence: 60, reasoning: "관찰" },
      ],
    },
  };
}

const recent = report("recent", "2026-11-13T00:00:00Z");
const older = report("older", "2026-11-12T00:00:00Z");

function detail(summary, provider) {
  return {
    ...summary,
    report_inputs: {
      ...summary.report_inputs,
      tickers: { "005930": { provider, is_stale: false, last_trading_date: "2026-11-13" } },
    },
  };
}

function selectOlder() {
  const section = screen.getByRole("heading", { name: "국내 리포트 이력" }).closest("section");
  fireEvent.click(within(section).getAllByRole("button")[1]);
}

describe("Reports detail loading", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    window.localStorage.clear();
    api.reports.latest.mockResolvedValue({ domestic: recent, global: null });
    api.reports.list.mockResolvedValue([recent, older]);
    api.assets.list.mockResolvedValue([{ ticker: "005930" }]);
    api.settings.get.mockResolvedValue({ candidate_horizon: "medium" });
    api.reports.get.mockImplementation((id) =>
      Promise.resolve(
        detail(
          id === "recent" ? recent : older,
          id === "recent" ? "recent-provider" : "older-provider",
        ),
      ),
    );
  });

  it("loads the selected report snapshot and preserves historical data-quality details", async () => {
    render(<Reports />);
    expect(await screen.findByText(/제공자 recent-provider/)).toBeInTheDocument();
    selectOlder();
    expect(await screen.findByText(/제공자 older-provider/)).toBeInTheDocument();
    expect(screen.queryByText(/제공자 recent-provider/)).not.toBeInTheDocument();
  });

  it("ignores an earlier detail response after the user selects another report", async () => {
    let resolveRecent;
    api.reports.get.mockImplementation((id) =>
      id === "recent"
        ? new Promise((resolve) => {
            resolveRecent = resolve;
          })
        : Promise.resolve(detail(older, "older-provider")),
    );
    render(<Reports />);
    await waitFor(() => expect(resolveRecent).toBeTypeOf("function"));
    selectOlder();
    expect(await screen.findByText(/제공자 older-provider/)).toBeInTheDocument();
    await act(async () => resolveRecent(detail(recent, "recent-provider")));
    expect(screen.getByText(/제공자 older-provider/)).toBeInTheDocument();
    expect(screen.queryByText(/제공자 recent-provider/)).not.toBeInTheDocument();
  });

  it("retries a failed detail read without losing the report list", async () => {
    api.reports.get.mockRejectedValueOnce(new Error("상세 조회 일시 실패"));
    render(<Reports />);
    expect(await screen.findByText("상세 조회 일시 실패")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(await screen.findByText(/제공자 recent-provider/)).toBeInTheDocument();
    selectOlder();
    expect(await screen.findByText(/제공자 older-provider/)).toBeInTheDocument();
  });
});
