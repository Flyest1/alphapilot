import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import TopStrategies from "./TopStrategies.jsx";

describe("TopStrategies", () => {
  it("ranks by the pre-calibration score and shows downside calibration", () => {
    render(
      <TopStrategies
        strategies={[
          {
            ticker: "MID",
            name: "Mid",
            action: "BUY",
            confidence: 70,
            confidence_detail: { calibrated: false, base_confidence: 70 },
          },
          {
            ticker: "HIGH",
            name: "High",
            action: "BUY",
            confidence: 60,
            confidence_detail: {
              calibrated: true,
              base_confidence: 100,
              calibration_factor: 0.6,
            },
          },
        ]}
      />,
    );

    const scoreTexts = screen.getAllByText(/보정 전 점수/);
    expect(scoreTexts[0]).toHaveTextContent("보정 전 점수 100/100");
    expect(scoreTexts[0]).toHaveTextContent("성과 경고 ×0.6");
  });
});
