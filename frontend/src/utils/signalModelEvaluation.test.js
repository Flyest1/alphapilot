import { describe, expect, it } from "vitest";

import { formatEvaluationValue, signalModelEvaluationView } from "./signalModelEvaluation.js";

describe("signalModelEvaluation", () => {
  it("keeps missing values unavailable while preserving real zero percentages", () => {
    expect(formatEvaluationValue("success_rate", null)).toBe("-");
    expect(formatEvaluationValue("success_rate", 0)).toBe("0.00%");
    expect(formatEvaluationValue("run_count", 0)).toBe("0");
    expect(formatEvaluationValue("threshold_state", "unconfigured")).toBe("미설정");
  });

  it("normalizes the approved read-only evaluation contract", () => {
    const view = signalModelEvaluationView({
      schema_version: "signal-model-evaluation-v1",
      availability: "available",
      state: "review_ready",
      research_only: true,
      adoption_permitted: false,
      evaluation_window_weeks: 12,
      champion: { version: "technical-v1" },
      challenger: { version: "signal-v2" },
      active_evaluation: {
        expected_observation_count: 40,
        observed_observation_count: 36,
        excluded_observation_count: 2,
      },
      samples: { official_scheduled: 8, manual_input_links: 2 },
      thresholds: { state: "unconfigured", values: null },
    });

    expect(view.status.label).toBe("검토 준비");
    expect(view.period).toBe("12주");
    expect(view.versions.map((row) => row.value)).toEqual(["technical-v1", "signal-v2"]);
    expect(view.counts.map((row) => row.value)).toEqual(["40", "36", "2"]);
    expect(view.samples.map((row) => row.value)).toEqual(["8", "2"]);
  });

  it("keeps absent values unavailable for migration-required status", () => {
    const view = signalModelEvaluationView({
      availability: "migration_required",
      state: "not_configured",
      samples: { official_scheduled: null, manual_input_links: null },
    });

    expect(view.status.label).toBe("마이그레이션 필요");
    expect(view.counts.map((row) => row.value)).toEqual(["-", "-", "-"]);
    expect(view.samples.map((row) => row.value)).toEqual(["-", "-"]);
  });

  it("handles an unavailable endpoint without implying a result", () => {
    expect(signalModelEvaluationView(null, { status: 404 }).status.label).toBe("기능 준비 중");
    expect(signalModelEvaluationView({ availability: "unavailable" }).status.label).toBe(
      "사용 불가",
    );
  });

  it("suppresses cached values after a refresh error", () => {
    const view = signalModelEvaluationView(
      {
        availability: "available",
        state: "collecting",
        evaluation_window_weeks: 12,
        champion: { version: "stale-v1" },
        samples: { official_scheduled: 5, manual_input_links: 2 },
      },
      { status: 503 },
    );

    expect(view.status.label).toBe("사용 불가");
    expect(view.period).toBe("-");
    expect(view.versions.map((row) => row.value)).toEqual([undefined, undefined]);
    expect(view.samples.map((row) => row.value)).toEqual(["-", "-"]);
  });
});
