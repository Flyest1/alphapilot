import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ReportContent from "./ReportContent.jsx";

describe("ReportContent", () => {
  it("keeps news sources internal while preserving the report narrative", () => {
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
        }}
      />,
    );

    expect(screen.getByText("반도체 수요가 개선됐습니다.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "시장 주요 동향" })).toBeInTheDocument();
    expect(screen.queryByText(/example\.com|GDELT|뉴스 3건 반영/)).not.toBeInTheDocument();
  });
});
