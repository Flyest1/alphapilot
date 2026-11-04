import { describe, expect, it } from "vitest";

import { displayReportText } from "./reports.js";

describe("report display text", () => {
  it("hides legacy news evidence ids, sites, and URLs", () => {
    expect(
      displayReportText(
        "GDELT 반도체 수요가 개선됐습니다. [N1 · Reuters · example.com · 2026-07-18] news.example.org 참고",
      ),
    ).toBe("반도체 수요가 개선됐습니다. 참고");
    expect(displayReportText("추가 참고 https://news.example.com/story")).toBe("추가 참고");
  });

  it("keeps tickers and ordinary bracketed notes", () => {
    expect(displayReportText("삼성전자(005930.KS) 반등")).toBe("삼성전자(005930.KS) 반등");
    expect(displayReportText("[ETF 집중 주의] 비중 확인")).toBe("[ETF 집중 주의] 비중 확인");
    expect(displayReportText("[Fed meeting] 금리")).toBe("[Fed meeting] 금리");
    expect(displayReportText("[E2 · source: filing] 공시 확인")).toBe("공시 확인");
  });
});
