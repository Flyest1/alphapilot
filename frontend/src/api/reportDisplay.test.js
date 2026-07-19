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
});
