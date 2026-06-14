import { describe, expect, it } from "vitest";

import { confidenceBadge, groupTitle, statsHeadlines } from "./recommendationStats.js";

const stats = {
  groups: [
    {
      action: "BUY",
      horizon: "medium",
      score_band: "70s",
      closed_count: 22,
      win_rate: 0.64,
    },
    {
      action: "SELL",
      horizon: "short",
      score_band: "60s",
      closed_count: 3, // 표본 부족 → 핵심 요약 제외
      win_rate: 1,
    },
    {
      action: "WATCH",
      horizon: "long",
      score_band: "80_plus",
      closed_count: 10,
      win_rate: null, // 승률 없음 → 제외
    },
  ],
};

describe("groupTitle", () => {
  it("combines action, horizon, and band labels in Korean", () => {
    expect(groupTitle(stats.groups[0])).toBe("매수 · 중기 20거래일 · 점수 70대");
  });
});

describe("statsHeadlines", () => {
  it("creates headline sentences only for groups with enough closed samples", () => {
    const headlines = statsHeadlines(stats);

    expect(headlines).toHaveLength(1);
    expect(headlines[0].text).toBe(
      "매수 · 중기 20거래일 · 점수 70대 추천의 목표 도달 승률 64% (종료 표본 22건)",
    );
  });

  it("returns an empty list without stats", () => {
    expect(statsHeadlines(null)).toEqual([]);
  });
});

describe("confidenceBadge", () => {
  it("returns null without detail", () => {
    expect(confidenceBadge(null)).toBeNull();
  });

  it("labels calibrated and uncalibrated details", () => {
    expect(confidenceBadge({ calibrated: true }).label).toBe("승률 보정됨");
    expect(confidenceBadge({ calibrated: false }).label).toBe("보정 전(표본 부족)");
  });
});
