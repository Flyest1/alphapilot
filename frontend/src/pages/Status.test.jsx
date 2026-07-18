import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  system: { status: vi.fn() },
}));

vi.mock("../api/client.js", () => ({
  api,
  isApiCacheFresh: vi.fn(() => false),
  readApiCache: vi.fn(() => null),
}));

vi.mock("../api/reports.js", () => ({
  formatReportTime: (value) => value || "-",
  generationModeLabel: (value) => value?.mode || "-",
}));

import Status from "./Status.jsx";

describe("Status page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.system.status.mockResolvedValue({
      backend: { status: "ok", app_env: "production" },
      database: { status: "ok", provider: "supabase", configured: true },
      openai: { configured: true },
      data_providers: {
        sec_edgar: {
          configured: true,
          cache: {
            entry_count: 8,
            size_bytes: 1536,
            max_entries: 100,
            max_size_bytes: 1048576,
          },
        },
        fred: { configured: true },
      },
      assets: {},
      candidate_assets: {},
      reports: {},
      scheduler: {},
      report_jobs: {},
      portfolio_snapshots: {},
      recommendation_cycles: {},
      advisory_jobs: { active_count: 1, queued_count: 2, max_workers: 3 },
    });
  });

  it("shows SEC cache and advisory runner metrics when the backend provides them", async () => {
    render(<Status />);

    await waitFor(() => expect(api.system.status).toHaveBeenCalled());
    expect(await screen.findByText("SEC EDGAR 캐시 항목")).toBeInTheDocument();
    expect(screen.getByText("8개 / 최대 100개")).toBeInTheDocument();
    expect(screen.getByText("1.5 KB / 최대 1.0 MB")).toBeInTheDocument();
    expect(screen.getByText("자문 작업 실행")).toBeInTheDocument();
    expect(screen.getByText("활성 1개 · 대기 2개")).toBeInTheDocument();
    expect(screen.getByText("최대 3개")).toBeInTheDocument();
  });
});
