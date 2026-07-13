import { describe, expect, it } from "vitest";

import { generationModeLabel, isTechnicalOnlyReport } from "./reports.js";

describe("report generation metadata", () => {
  it("prefers generation metadata over legacy narrative markers", () => {
    expect(
      isTechnicalOnlyReport({
        report_inputs: { ai_generation: { mode: "ai_narrative" } },
        content: { key_risks: ["AI reasoning unavailable for this report"] },
      }),
    ).toBe(false);
    expect(
      isTechnicalOnlyReport({ report_inputs: { ai_generation: { mode: "technical_only" } } }),
    ).toBe(true);
  });

  it("keeps legacy fallback detection and labels modes", () => {
    expect(
      isTechnicalOnlyReport({
        content: { key_risks: ["AI reasoning unavailable for this report"] },
      }),
    ).toBe(true);
    expect(generationModeLabel({ mode: "ai_narrative" })).toBe("AI 설명 사용");
    expect(generationModeLabel({ mode: "technical_only" })).toBe("기술분석 fallback");
  });
});
