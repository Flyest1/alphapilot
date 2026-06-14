import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import RebalanceCard from "./RebalanceCard.jsx";

const summary = {
  allocation_drift: [
    {
      key: "domestic",
      label: "국내",
      target_pct: 40,
      actual_pct: 70,
      drift_pct: 30,
      exceeded: true,
    },
    { key: "cash", label: "현금", target_pct: 20, actual_pct: 30, drift_pct: 10, exceeded: true },
  ],
  rebalance_suggestions: ["국내 비중이 목표(40%)보다 30.0%p 높습니다. 비중 축소를 검토하세요."],
};

describe("RebalanceCard", () => {
  it("renders nothing without drift data", () => {
    const { container } = render(<RebalanceCard summary={{}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows target vs actual and suggestions", () => {
    render(<RebalanceCard summary={summary} />);

    expect(screen.getByText("목표 대비 드리프트")).toBeInTheDocument();
    expect(screen.getByText("국내 (목표 40%)")).toBeInTheDocument();
    expect(screen.getByText(/\(\+30%p\)/)).toBeInTheDocument();
    expect(screen.getByText(/비중 축소를 검토하세요/)).toBeInTheDocument();
  });
});
