import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ReportContent from "./ReportContent.jsx";

function renderReport(overrides = {}) {
  render(
    <ReportContent
      candidateCount={0}
      dataLimitedCountValue={0}
      ownedCount={0}
      performanceLogs={[]}
      selected={{
        report_type: "global",
        created_at: "2026-07-18T00:00:00Z",
        report_inputs: {
          news_context: {
            status: "ok",
            article_count: 3,
            provider: "gdelt_doc_2_0",
          },
        },
        content: {
          market_summary: {
            summary:
              "반도체 수요가 개선됐습니다. [N1 · example.com · 2026-07-18 · https://example.com/a]",
            macro_factors: [
              "금리 방향을 확인해야 합니다. [N2 · news.example.com · 2026-07-18 · https://news.example.com/b]",
            ],
            key_indices: [],
          },
          asset_strategies: [],
          opportunities: [],
          key_risks: [],
        },
        ...overrides,
      }}
    />,
  );
}

describe("ReportContent", () => {
  it("keeps news sources internal while preserving the report narrative", () => {
    renderReport();

    expect(screen.getByText("반도체 수요가 개선됐습니다.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "시장 주요 동향" })).toBeInTheDocument();
    expect(screen.queryByText(/example\.com|GDELT/)).not.toBeInTheDocument();
  });

  it("keeps the news availability badge without naming the provider", () => {
    renderReport();

    expect(screen.getByText("뉴스 3건 반영")).toBeInTheDocument();
  });

  it("labels a rate-limited news pipeline without naming the provider", () => {
    renderReport({
      report_inputs: {
        news_context: {
          status: "unavailable",
          article_count: 0,
          provider: "gdelt_doc_2_0",
          failure_reasons: ["rate_limited"],
        },
      },
    });

    expect(screen.getByText("뉴스 제한: 호출량 초과")).toBeInTheDocument();
    expect(screen.queryByText(/GDELT/)).not.toBeInTheDocument();
  });

  it("drops list entries that redaction emptied instead of rendering blank bullets", () => {
    renderReport({
      content: {
        market_summary: {
          summary: "요약입니다.",
          macro_factors: ["[N1 · https://example.com/a]", "금리 방향을 확인해야 합니다."],
          key_indices: [],
        },
        asset_strategies: [],
        opportunities: [],
        key_risks: [],
      },
    });

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent("금리 방향을 확인해야 합니다.");
  });
});
