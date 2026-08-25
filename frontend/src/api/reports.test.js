import { describe, expect, it } from "vitest";

import {
  generationModeLabel,
  importantStrategyMessages,
  isTechnicalOnlyReport,
} from "./reports.js";

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

describe("important strategy messages", () => {
  it("uses the pre-calibration score for rank and exposes downside calibration", () => {
    const messages = importantStrategyMessages([
      {
        ticker: "HIGH",
        action: "BUY",
        confidence: 60,
        confidence_detail: {
          calibrated: true,
          base_confidence: 100,
          calibration_factor: 0.6,
        },
      },
      {
        ticker: "MID",
        action: "BUY",
        confidence: 70,
        confidence_detail: { calibrated: false, base_confidence: 70 },
      },
    ]);

    expect(messages[0].strategy.ticker).toBe("HIGH");
    expect(messages[0].exitLine).toContain("보정 전 점수 100/100");
    expect(messages[0].exitLine).toContain("과거 성과 경고 ×0.6");
  });
});
