import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PerformancePanel from "./PerformancePanel.jsx";

describe("PerformancePanel", () => {
  it("defers heavy performance data until the user asks for it", () => {
    const onLoad = vi.fn();

    render(<PerformancePanel selectedTickerCount={3} onLoad={onLoad} />);

    expect(screen.getByText("성과 추적 데이터")).toBeInTheDocument();
    expect(screen.getByText("3개 선택 종목")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "추천 생애주기와 성과 로그 보기" }));

    expect(onLoad).toHaveBeenCalledTimes(1);
  });

  it("shows cycle and log summaries after performance data is loaded", () => {
    render(
      <PerformancePanel
        isLoaded
        cycles={[
          {
            id: "cycle-1",
            ticker: "005930",
            action: "BUY",
            horizon: "short",
            status: "active",
            reference_price: 70000,
          },
        ]}
        logs={[
          {
            id: "log-1",
            ticker: "005930",
            action: "BUY",
            price_at_recommendation: 70000,
            return_after_1d: 1.2,
          },
        ]}
      />,
    );

    expect(screen.getByText("추천 생애주기")).toBeInTheDocument();
    expect(screen.getByText("기존 성과 로그")).toBeInTheDocument();
    expect(screen.getAllByText("1개 연결")).toHaveLength(2);
    expect(screen.getByText("평가 로그")).toBeInTheDocument();
  });
});
