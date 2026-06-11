import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import StrategyTable from "./StrategyTable.jsx";

const strategies = [
  {
    ticker: "005930",
    name: "삼성전자",
    action: "BUY",
    confidence: 82,
    current_price: 79000,
    buy_range_low: 77000,
    buy_range_high: 80000,
    target_price: 88000,
    stop_loss: 73000,
    reasoning: "기술 점수 82",
  },
  {
    ticker: "035720",
    name: "Kakao",
    action: "WATCH",
    confidence: 0,
    current_price: null,
    reasoning: "data-limited",
  },
];

describe("StrategyTable", () => {
  it("shows an empty state without strategies", () => {
    render(<StrategyTable strategies={[]} />);
    expect(screen.getByText("표시할 전략이 없습니다.")).toBeInTheDocument();
  });

  it("renders strategy rows with action labels and prices", () => {
    render(<StrategyTable performanceLogs={[]} strategies={strategies} />);

    expect(screen.getByText("005930")).toBeInTheDocument();
    expect(screen.getByText("매수")).toBeInTheDocument();
    expect(screen.getByText("79,000")).toBeInTheDocument();
  });

  it("marks data-limited strategies with a status pill", () => {
    render(<StrategyTable performanceLogs={[]} strategies={strategies} />);

    expect(screen.getAllByText("데이터 제한").length).toBeGreaterThan(0);
  });

  it("shows performance returns when a matching log exists", () => {
    render(
      <StrategyTable
        performanceLogs={[{ ticker: "005930", action: "BUY", return_after_5d: 4.2 }]}
        strategies={[strategies[0]]}
      />,
    );

    expect(screen.getByText("4.20%")).toBeInTheDocument();
  });
});
