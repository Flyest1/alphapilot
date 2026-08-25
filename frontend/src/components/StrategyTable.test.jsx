import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import StrategyTable from "./StrategyTable.jsx";

const strategy = {
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
};

function renderStrategy(overrides = {}, inputsByTicker) {
  return render(
    <StrategyTable
      inputsByTicker={inputsByTicker}
      performanceLogs={[]}
      strategies={[{ ...strategy, ...overrides }]}
    />,
  );
}

describe("StrategyTable", () => {
  it("shows an empty state without strategies", () => {
    render(<StrategyTable strategies={[]} />);

    expect(screen.getByText("표시할 전략이 없습니다.")).toBeInTheDocument();
  });

  it("renders the pre-calibration score, not a probability", () => {
    renderStrategy();

    expect(screen.getByText("보정 전 점수")).toBeInTheDocument();
    expect(screen.getByText("82 /100")).toBeInTheDocument();
    expect(screen.queryByText("82%")).not.toBeInTheDocument();
  });

  it("shows downside calibration as a warning without replacing the main score", () => {
    renderStrategy({
      confidence: 60,
      confidence_detail: {
        calibrated: true,
        base_confidence: 100,
        technical_confidence: 100,
        calibration_factor: 0.6,
        win_rate: 0.1,
        sample_size: 30,
      },
    });

    expect(screen.getByText("과거 성과 경고")).toBeInTheDocument();
    expect(screen.getByText("100 /100")).toBeInTheDocument();
    expect(screen.getByText(/참고 신뢰도 60/)).toBeInTheDocument();
  });

  it("keeps rendering legacy position sizing", () => {
    renderStrategy({
      position_sizing: {
        suggested_max_amount: 200000,
        risk_per_trade_pct: 1,
        stop_distance_pct: 8,
        currency: "KRW",
        method: "fixed-fractional",
      },
    });

    expect(screen.getByText("검토용 투입 금액 상한(모델 추정)")).toBeInTheDocument();
    expect(screen.getByText(/제안 상한: 200,000 KRW/)).toBeInTheDocument();
    expect(screen.getByText(/주문 수량이 아닙니다/)).toBeInTheDocument();
  });

  it("shows a binding constraint and readable constraint details", () => {
    renderStrategy({
      position_sizing: {
        suggested_max_amount: 200000,
        binding_constraint: "remaining_cash",
        constraints: {
          remaining_cash: { status: "available", amount: 200000 },
          fixed_risk: { status: "available", amount: 250000 },
          beta: { status: "unavailable", amount: null },
        },
      },
    });

    expect(screen.getByText("결정 제약: 남은 현금 예산")).toBeInTheDocument();
    expect(
      screen.getByText(/적용 한도: 남은 현금 예산 200,000, 개별 손실 예산 250,000/),
    ).toBeInTheDocument();
    expect(screen.getByText("미산출 사유: 포트폴리오 베타")).toBeInTheDocument();
  });

  it("shows an unavailable expected value for low samples", () => {
    renderStrategy({
      position_sizing: { expected_value: { status: "insufficient", sample_size: 8 } },
    });

    expect(screen.getByText("기대값 미산출: 표본 또는 데이터 품질 부족")).toBeInTheDocument();
  });

  it("shows all available expected-value scenario details", () => {
    renderStrategy({
      position_sizing: {
        expected_value: {
          status: "available",
          target_hit_frequency: 0.42,
          stop_hit_frequency: 0.18,
          other_frequency: 0.4,
          sample_size: 120,
          upside_pct: 8.5,
          downside_pct: 4.2,
          cost_pct: 0.3,
          expected_value_pct: 2.11,
        },
      },
    });

    expect(screen.getByText("과거 검증 기반 시나리오 기대값(보장 아님)")).toBeInTheDocument();
    expect(screen.getByText(/목표 도달 빈도: 42.00%/)).toBeInTheDocument();
    expect(screen.getByText(/손절 도달 빈도: 18.00%/)).toBeInTheDocument();
    expect(screen.getByText(/기타 결과 빈도: 40.00%/)).toBeInTheDocument();
    expect(screen.getByText(/표본 수: 120건/)).toBeInTheDocument();
    expect(screen.getByText(/상승 시나리오: 8.50%/)).toBeInTheDocument();
    expect(screen.getByText(/하락 시나리오: 4.20%/)).toBeInTheDocument();
    expect(screen.getByText(/비용: 0.30%/)).toBeInTheDocument();
    expect(screen.getByText(/기대값\(EV\): 2.11%/)).toBeInTheDocument();
  });

  it("omits invalid amounts while preserving signed analytical metrics", () => {
    renderStrategy({
      confidence: -5,
      position_sizing: {
        suggested_max_amount: Number.NaN,
        risk_per_trade_pct: -1,
        stop_distance_pct: Number.POSITIVE_INFINITY,
        risk_metrics: { volatility: -2, gap: Number.NaN, beta: -0.4, max_correlation: Infinity },
        expected_value: {
          status: "available",
          target_hit_frequency: -0.2,
          stop_hit_frequency: Number.NaN,
          other_frequency: Infinity,
          sample_size: -1,
          upside_pct: -4,
          downside_pct: Number.NaN,
          cost_pct: Infinity,
          expected_value_pct: -2,
        },
      },
    });

    expect(screen.getByText("- /100")).toBeInTheDocument();
    expect(screen.queryByText(/NaN|Infinity|-1\.00%/)).not.toBeInTheDocument();
    expect(screen.getByText(/위험 지표: 베타 -0.4/)).toBeInTheDocument();
    expect(screen.getByText(/기대값\(EV\): -2.00%/)).toBeInTheDocument();
  });

  it("marks insufficient data-quality notes as data limited", () => {
    renderStrategy(
      {},
      {
        "005930": {
          provider: "pykrx",
          last_trading_date: "2026-06-10T00:00:00+00:00",
          is_stale: false,
          data_quality_note: "short history; insufficient indicators",
        },
      },
    );

    expect(screen.getByText(/제공자 pykrx/)).toBeInTheDocument();
    expect(screen.getByText(/데이터 제한/)).toBeInTheDocument();
  });
});
