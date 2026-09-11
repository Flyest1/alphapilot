import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import SummaryCards from "./SummaryCards.jsx";
import AllocationChart from "./AllocationChart.jsx";

describe("portfolio valuation coverage", () => {
  it("shows unavailable returns and partial coverage without zero gain", () => {
    render(
      <SummaryCards
        summary={{
          valuation_status: "partial",
          valued_asset_count: 1,
          total_asset_count: 2,
          valued_market_value: 1000,
          cash_value: 1000,
          total_market_value: null,
          total_profit_loss: null,
          total_return_rate: null,
          total_net_return_rate: null,
          daily_profit_loss: null,
        }}
      />,
    );
    expect(screen.getAllByText("계산 불가")).toHaveLength(5);
    expect(screen.getByText(/평가 가능 1\/2개/)).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });
  it("does not show unavailable asset weights as percentages", () => {
    render(<AllocationChart allocation={[{ ticker: "ABC", name: "Asset", weight: null }]} />);
    expect(screen.getByText("평가 불가")).toBeInTheDocument();
  });
});
