import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SignalModelEvaluationPanel from "./SignalModelEvaluationPanel.jsx";

describe("SignalModelEvaluationPanel", () => {
  it("always presents the approved evaluation contract as read-only research", () => {
    render(
      <SignalModelEvaluationPanel
        evaluation={{
          schema_version: "signal-model-evaluation-v1",
          availability: "available",
          state: "review_ready",
          research_only: true,
          adoption_permitted: false,
          evaluation_window_weeks: 12,
          champion: { version: "technical-v1" },
          challenger: { version: "signal-v2" },
          active_evaluation: {
            expected_observation_count: 12,
            observed_observation_count: 10,
            excluded_observation_count: 1,
          },
          samples: { official_scheduled: 2, manual_input_links: 1 },
          thresholds: { state: "unconfigured", values: null },
          promotion: { automatic: false, eligible: null },
        }}
      />,
    );

    expect(screen.getByText("연구 전용")).toBeInTheDocument();
    expect(screen.getByText("운영 미반영")).toBeInTheDocument();
    expect(screen.getByText("수동 승격만")).toBeInTheDocument();
    expect(screen.getByText("12주")).toBeInTheDocument();
    expect(screen.getByText("technical-v1")).toBeInTheDocument();
    expect(screen.getByText("signal-v2")).toBeInTheDocument();
    expect(screen.getByText("예상 관측")).toBeInTheDocument();
    expect(screen.getByText("관측 완료")).toBeInTheDocument();
    expect(screen.getByText("제외 관측")).toBeInTheDocument();
    expect(screen.getByText("미설정")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows a non-blocking migration-required state", () => {
    render(<SignalModelEvaluationPanel evaluation={{ availability: "migration_required" }} />);

    expect(screen.getByText("마이그레이션 필요")).toBeInTheDocument();
    expect(screen.getByText(/데이터베이스 마이그레이션이 필요합니다/)).toBeInTheDocument();
    expect(screen.getAllByText("-")).toHaveLength(9);
  });
});
