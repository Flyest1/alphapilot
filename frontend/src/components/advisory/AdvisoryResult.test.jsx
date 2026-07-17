import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AdvisoryResult from "./AdvisoryResult.jsx";

describe("AdvisoryResult", () => {
  it.each([
    ["partial", "일부 데이터가 제한되어 결과를 전체 판단으로 사용할 수 없습니다."],
    ["limited", "데이터가 제한되어 일부 결과만 참고용으로 확인해야 합니다."],
    ["data-limited", "필수 데이터가 제한되어 수치와 판단을 그대로 신뢰할 수 없습니다."],
    ["unavailable", "필수 데이터가 없어 이 결과는 평가 불가 상태입니다."],
    ["insufficient_data", "근거가 부족해 충분한 분석을 수행할 수 없습니다."],
  ])("shows a prominent warning for %s data quality", (status, message) => {
    render(
      <AdvisoryResult
        analysis={{
          result: {
            data_quality: { status },
            disclaimer: "의사결정 지원 정보입니다.",
          },
        }}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(message);
  });

  it.each([
    ["not_configured", "OpenAI 자문 설명이 설정되지 않아 결정론적 분석만 표시합니다."],
    ["failed", "AI 설명 생성에 실패해 결정론적 분석만 표시합니다."],
    ["no_evidence", "인용 가능한 근거가 없어 AI 설명을 생성하지 않았습니다."],
  ])("shows the AI narrative status %s", (status, message) => {
    render(
      <AdvisoryResult
        analysis={{
          result: {
            data_quality: { status: "available" },
            ai_narrative_status: status,
            disclaimer: "의사결정 지원 정보입니다.",
          },
        }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(message);
  });

  it("supports the structured backend AI narrative status", () => {
    render(
      <AdvisoryResult
        analysis={{
          result: {
            data_quality: { status: "available" },
            ai_narrative_status: {
              status: "unavailable",
              reason: "generation_failed",
              provider: "openai",
            },
            disclaimer: "의사결정 지원 정보입니다.",
          },
        }}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "AI 설명 생성에 실패해 결정론적 분석만 표시합니다.",
    );
  });

  it("renders generic result sections and data limitations", () => {
    render(
      <AdvisoryResult
        analysis={{
          created_at: "2026-07-17T09:00:00Z",
          result: {
            as_of: "2026-07-16",
            summary: "밸류에이션과 실적 회복 조건을 함께 확인합니다.",
            tables: { top_candidates: [{ ticker: "AAPL", score: 82 }] },
            rankings: [{ ticker: "AAPL", rank: 1 }],
            scenarios: [{ name: "균형", allocation: "60/40" }],
            evidence: ["최근 실적 발표"],
            data_quality: { provider: "yfinance", missing_fields: ["guidance"] },
            limitations: ["공시 지연 가능성"],
          },
        }}
      />,
    );

    expect(screen.getByText("자문 결과")).toBeInTheDocument();
    expect(screen.getByText("데이터 기준시각")).toBeInTheDocument();
    expect(screen.getByText("2026-07-16")).toBeInTheDocument();
    expect(screen.getAllByText("누락 필드")).toHaveLength(2);
    expect(screen.getAllByText("guidance")).toHaveLength(2);
    expect(screen.getByText("한계")).toBeInTheDocument();
    expect(screen.getByText("공시 지연 가능성")).toBeInTheDocument();
    expect(screen.getByText("분석 표")).toBeInTheDocument();
    expect(screen.getByText("순위")).toBeInTheDocument();
    expect(screen.getByText("시나리오")).toBeInTheDocument();
    expect(screen.getByText("근거")).toBeInTheDocument();
    expect(screen.getByText("데이터 품질")).toBeInTheDocument();
  });

  it("maps feature-specific arrays into the shared table and ranking sections", () => {
    render(
      <AdvisoryResult
        analysis={{
          result: {
            disclaimer: "의사결정 지원 정보입니다.",
            rows: [{ ticker: "MSFT", score: 76 }],
            top_candidates: [{ ticker: "MSFT", rank: 1 }],
          },
        }}
      />,
    );

    expect(screen.getByText("분석 표")).toBeInTheDocument();
    expect(screen.getByText("순위")).toBeInTheDocument();
    expect(screen.getAllByText("MSFT")).toHaveLength(2);
  });

  it("renders traceable evidence links and Korean status labels", () => {
    render(
      <AdvisoryResult
        analysis={{
          result: {
            risk_rating: "relative_low_risk",
            evidence: [
              {
                evidence_id: "S1",
                title: "최근 10-Q",
                provider: "sec_edgar",
                url: "https://www.sec.gov/example",
              },
            ],
            data_quality: {
              status: "partial",
              providers: ["sec_edgar"],
              source_as_of: "2026-07-15",
              retrieved_at: "2026-07-17T09:00:00Z",
            },
            disclaimer: "투자 의사결정 지원 정보입니다.",
          },
        }}
      />,
    );

    expect(screen.getAllByText("2026-07-15").length).toBeGreaterThan(0);
    expect(screen.getAllByText("sec_edgar").length).toBeGreaterThan(0);
    expect(screen.getByText("상대적 위험 낮음")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "원문 열기" })).toHaveAttribute(
      "href",
      "https://www.sec.gov/example",
    );
  });
});
