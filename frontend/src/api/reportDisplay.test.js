import { describe, expect, it } from "vitest";

import { displayReportText } from "./reports.js";

describe("report display text", () => {
  it("hides legacy news evidence ids, sites, publishers, and URLs", () => {
    expect(
      displayReportText(
        "GDELT 반도체 수요가 개선됐습니다. [N1 · Reuters · example.com · 2026-07-18] news.example.org 참고",
      ),
    ).toBe("반도체 수요가 개선됐습니다. 참고");
    expect(displayReportText("추가 참고 https://news.example.com/story")).toBe("추가 참고");
    expect(displayReportText("수요가 개선됐습니다 [[N1]].")).toBe("수요가 개선됐습니다.");
    expect(displayReportText("Reuters에 따르면 수요가 개선됐습니다.")).toBe(
      "에 따르면 수요가 개선됐습니다.",
    );
    expect(displayReportText("Bloomberg 보도에 따르면 금리는 유지됩니다.")).toBe(
      "보도에 따르면 금리는 유지됩니다.",
    );
    expect(displayReportText("출처: reuters.com")).toBe("");
  });

  it("keeps exchange-suffixed tickers, which a generic domain rule would delete", () => {
    expect(displayReportText("005930.KS: 기술 점수 기준 매수 후보")).toBe(
      "005930.KS: 기술 점수 기준 매수 후보",
    );
    expect(displayReportText("삼성전자(005930.KS)의 목표가를 상향합니다.")).toBe(
      "삼성전자(005930.KS)의 목표가를 상향합니다.",
    );
    expect(displayReportText("stale market data for: 005930.KS, 035720.KQ")).toBe(
      "시장 데이터가 지연된 종목: 005930.KS, 035720.KQ",
    );
    expect(displayReportText("TSMC(2330.TW)와 SCHD.US 비중")).toBe("TSMC(2330.TW)와 SCHD.US 비중");
  });

  it("keeps ordinary bracketed asides and decimal figures", () => {
    expect(displayReportText("[ETF 비중 조정] 필요")).toBe("[ETF 비중 조정] 필요");
    expect(displayReportText("[Fed 금리 인상] 우려")).toBe("[Fed 금리 인상] 우려");
    expect(displayReportText("반도체 업종 [PER 12배] 수준으로 회복했습니다.")).toBe(
      "반도체 업종 [PER 12배] 수준으로 회복했습니다.",
    );
    expect(displayReportText("실적은 [non-GAAP] 기준입니다.")).toBe(
      "실적은 [non-GAAP] 기준입니다.",
    );
    expect(displayReportText("목표가는 12.5% 상승, 배당은 2.0%입니다.")).toBe(
      "목표가는 12.5% 상승, 배당은 2.0%입니다.",
    );
  });
});
