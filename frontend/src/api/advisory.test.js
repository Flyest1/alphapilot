import { describe, expect, it, vi } from "vitest";

const { apiRequest } = vi.hoisted(() => ({ apiRequest: vi.fn() }));

vi.mock("./client.js", () => ({ apiRequest }));

import {
  createAdvisoryJob,
  getAdvisoryAnalysis,
  getAdvisoryJob,
  getAdvisoryStatus,
  listAdvisoryAnalyses,
} from "./advisory.js";

describe("advisory API", () => {
  it("uses the advisory jobs and analyses endpoints", () => {
    createAdvisoryJob({ analysis_type: "sector_outlook" });
    getAdvisoryJob("job-1");
    getAdvisoryAnalysis("analysis-1");
    listAdvisoryAnalyses();
    getAdvisoryStatus();

    expect(apiRequest).toHaveBeenNthCalledWith(1, "/api/advisory/jobs", {
      method: "POST",
      body: JSON.stringify({ analysis_type: "sector_outlook" }),
    });
    expect(apiRequest).toHaveBeenNthCalledWith(2, "/api/advisory/jobs/job-1");
    expect(apiRequest).toHaveBeenNthCalledWith(3, "/api/advisory/analyses/analysis-1");
    expect(apiRequest).toHaveBeenNthCalledWith(4, "/api/advisory/analyses");
    expect(apiRequest).toHaveBeenNthCalledWith(5, "/api/advisory/status");
  });
});
