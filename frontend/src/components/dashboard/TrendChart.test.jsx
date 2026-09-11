import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import TrendChart from "./TrendChart.jsx";

describe("TrendChart missing valuation", () => {
  it("shows unknown daily return rather than zero percent", () => {
    render(
      <TrendChart
        chartRange="7d"
        onChangeRange={() => {}}
        summary={{
          daily_return_rate: null,
          cash_value: 1000,
          value_history: [],
          daily_asset_changes: [],
        }}
      />,
    );
    expect(screen.getByText("일간 수익률 계산 불가")).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });
  it("does not draw a series from unknown valuations", () => {
    render(
      <TrendChart
        chartRange="7d"
        onChangeRange={() => {}}
        summary={{
          daily_return_rate: null,
          cash_value: 1000,
          value_history: [
            { date: "2026-09-01", total_market_value: null, daily_profit_loss: null },
            { date: "2026-09-02", total_market_value: null, daily_profit_loss: null },
          ],
        }}
      />,
    );
    expect(screen.getByText("차트로 표시할 기간 데이터가 아직 부족합니다.")).toBeInTheDocument();
  });
});
