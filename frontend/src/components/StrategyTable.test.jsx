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

  it("shows calibration badge and confidence breakdown when detail exists", () => {
    render(
      <StrategyTable
        performanceLogs={[]}
        strategies={[
          {
            ...strategies[0],
            confidence: 78,
            confidence_detail: {
              technical_confidence: 60,
              win_rate: 0.8,
              sample_size: 30,
              calibrated: true,
              calibration_factor: 1.3,
              news_context_used: true,
            },
          },
        ]}
      />,
    );

    expect(screen.getByText("승률 보정됨")).toBeInTheDocument();
    expect(screen.getByText(/기술 점수 기여 60/)).toBeInTheDocument();
    expect(screen.getByText(/과거 승률 80%/)).toBeInTheDocument();
  });

  it("shows suggested position sizing for new candidates", () => {
    render(
      <StrategyTable
        performanceLogs={[]}
        strategies={[
          {
            ...strategies[0],
            position_sizing: {
              suggested_max_amount: 200000,
              risk_per_trade_pct: 1,
              stop_distance_pct: 8,
              currency: "KRW",
              method: "fixed-fractional",
            },
          },
        ]}
      />,
    );

    expect(screen.getByText("제안 투입 한도")).toBeInTheDocument();
    expect(screen.getByText(/최대 약 200,000 KRW/)).toBeInTheDocument();
    expect(screen.getByText(/주문 수량이 아닙니다/)).toBeInTheDocument();
  });

  it("shows data quality badges from report inputs", () => {
    render(
      <StrategyTable
        inputsByTicker={{
          "005930": {
            provider: "pykrx",
            last_trading_date: "2026-06-10T00:00:00+00:00",
            is_stale: false,
          },
        }}
        performanceLogs={[]}
        strategies={[strategies[0]]}
      />,
    );

    expect(screen.getByText(/제공자 pykrx/)).toBeInTheDocument();
    expect(screen.getByText(/최근 거래일 2026-06-10/)).toBeInTheDocument();
    expect(screen.getByText(/데이터 최신/)).toBeInTheDocument();
  });
});
