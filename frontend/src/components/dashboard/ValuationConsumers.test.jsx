import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ExposurePanel from "./ExposurePanel.jsx";
import RebalanceCard from "./RebalanceCard.jsx";
import ReportContent from "../reports/ReportContent.jsx";

describe("nullable valuation consumers", () => {
  it("renders missing exposure without a zero allocation or rebalance suggestion", () => {
    const summary = {
      valuation_status: "partial",
      total_market_value: null,
      currency_exposure: [],
      market_exposure: [],
      sector_exposure: [],
      concentration_warnings: [],
      allocation_drift: [],
      rebalance_suggestions: [],
    };
    render(
      <>
        <ExposurePanel summary={summary} />
        <RebalanceCard summary={summary} />
      </>,
    );
    expect(screen.getByText("표시할 노출 데이터가 아직 없습니다.")).toBeInTheDocument();
    expect(screen.queryByText(/0%/)).not.toBeInTheDocument();
    expect(screen.queryByText("목표 대비 드리프트")).not.toBeInTheDocument();
  });
  it("preserves the data-limited warning on a report with nullable totals", () => {
    render(
      <ReportContent
        ownedCount={0}
        candidateCount={0}
        dataLimitedCountValue={1}
        performanceLogs={[]}
        selected={{
          content: {
            portfolio_summary: { total_market_value: null, total_return_rate: null },
            asset_strategies: [],
            key_risks: ["시세 누락으로 전체 평가액과 수익률을 계산할 수 없습니다."],
          },
        }}
      />,
    );
    expect(
      screen.getByText("시세 누락으로 전체 평가액과 수익률을 계산할 수 없습니다."),
    ).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });
});
