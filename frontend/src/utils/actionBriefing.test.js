import { describe, expect, it } from "vitest";

import { buildActionBriefing } from "./actionBriefing.js";

const NOW = new Date("2026-06-11T00:00:00Z").getTime();

const summary = {
  rebalance_suggestions: ["국내 비중이 목표(40%)보다 30.0%p 높습니다. 비중 축소를 검토하세요."],
  concentration_warnings: [],
};

const report = {
  content: {
    asset_strategies: [
      { ticker: "005930", name: "삼성전자", action: "REDUCE", confidence: 45, reasoning: "기술" },
      { ticker: "NVDA", name: "NVIDIA", action: "BUY", confidence: 82, reasoning: "기술" },
      { ticker: "AAPL", name: "Apple", action: "BUY", confidence: 75, reasoning: "기술" },
    ],
  },
  report_inputs: {
    tickers: {
      "005930": { is_stale: false },
      KAKAO: { is_stale: true },
    },
  },
};

const cycles = [
  {
    id: "c1",
    ticker: "069500",
    status: "hit_target",
    closed_at: "2026-06-10T01:00:00+00:00",
  },
  {
    id: "c2",
    ticker: "035720",
    status: "hit_stop",
    closed_at: "2026-06-09T01:00:00+00:00",
  },
  {
    id: "c3",
    ticker: "OLD",
    status: "hit_target",
    closed_at: "2026-05-01T01:00:00+00:00", // 오래된 종료 → 제외
  },
];

const assets = [{ ticker: "005930" }];

describe("buildActionBriefing", () => {
  it("collects target/stop hits, reduce checks, drift, candidates, and stale tickers", () => {
    const items = buildActionBriefing({ summary, report, cycles, assets, now: NOW });
    const kinds = items.map((item) => item.kind);

    expect(kinds).toContain("target");
    expect(kinds).toContain("stop");
    expect(kinds).toContain("reduce");
    expect(kinds).toContain("drift");
    expect(kinds).toContain("candidate");
    expect(kinds).toContain("stale");
    expect(items.find((item) => item.kind === "target").text).toContain("069500");
    expect(items.find((item) => item.kind === "reduce").text).toContain("005930");
    expect(items.find((item) => item.kind === "stale").text).toContain("KAKAO");
    // 7일이 지난 종료 cycle은 제외된다
    expect(items.some((item) => item.text.includes("OLD"))).toBe(false);
  });

  it("ranks new BUY candidates by confidence and excludes owned tickers", () => {
    const items = buildActionBriefing({ summary: {}, report, cycles: [], assets, now: NOW });
    const candidates = items.filter((item) => item.kind === "candidate");

    expect(candidates[0].text).toContain("NVDA");
    expect(candidates.some((item) => item.text.includes("005930"))).toBe(false);
  });

  it("returns an empty list without data", () => {
    expect(buildActionBriefing({ summary: {}, report: null, cycles: [], assets: [] })).toEqual([]);
  });
});
