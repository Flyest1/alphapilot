import { describe, expect, it } from "vitest";

import {
  ADVISORY_FEATURES,
  buildAdvisoryPayload,
  getAdvisoryFeature,
  validateAdvisoryPayload,
} from "./advisoryFeatures.js";

describe("advisory payloads", () => {
  it("defines all eight advisory analyses", () => {
    expect(ADVISORY_FEATURES).toHaveLength(8);
    expect(ADVISORY_FEATURES.map((feature) => feature.id)).toEqual([
      "undervalued_us_stocks",
      "etf_rebalancing",
      "post_earnings_opportunities",
      "ai_beneficiaries",
      "high_dividend_etfs",
      "sec_filing_risk",
      "etf_overlap",
      "sector_outlook",
    ]);
  });

  it("builds top-level stock analysis fields without a nested input object", () => {
    const payload = buildAdvisoryPayload(getAdvisoryFeature("undervalued_us_stocks"), {
      tickers: "aapl, MSFT AAPL",
    });

    expect(payload).toEqual({
      analysis_type: "undervalued_us_stocks",
      tickers: ["AAPL", "MSFT"],
      max_results: 5,
    });
    expect(payload).not.toHaveProperty("input");
  });

  it("builds ETF positions and accepts optional weights", () => {
    const feature = getAdvisoryFeature("etf_rebalancing");
    const payload = buildAdvisoryPayload(feature, {
      positions: [
        { ticker: "voo", weight_pct: "60" },
        { ticker: "qqq", weight_pct: "40" },
      ],
    });

    expect(payload).toEqual({
      analysis_type: "etf_rebalancing",
      positions: [
        { ticker: "VOO", weight_pct: 60 },
        { ticker: "QQQ", weight_pct: 40 },
      ],
    });
    expect(validateAdvisoryPayload(feature, payload)).toBe("");
    expect(
      buildAdvisoryPayload(feature, {
        positions: [{ ticker: "voo", weight_pct: "" }],
      }),
    ).toEqual({
      analysis_type: "etf_rebalancing",
      positions: [{ ticker: "VOO", weight_pct: null }],
    });
    expect(buildAdvisoryPayload(feature, { positions: [{ ticker: "", weight_pct: "" }] })).toEqual({
      analysis_type: "etf_rebalancing",
      positions: [],
    });
    expect(
      validateAdvisoryPayload(feature, { analysis_type: "etf_rebalancing", positions: [] }),
    ).toBe("");
    expect(
      validateAdvisoryPayload(feature, {
        analysis_type: "etf_rebalancing",
        positions: [{ ticker: "VOO", weight_pct: Number.NaN }],
      }),
    ).toMatch(/숫자/);
  });

  it("requires at least one ETF for overlap analysis", () => {
    const feature = getAdvisoryFeature("etf_overlap");

    expect(
      validateAdvisoryPayload(feature, { analysis_type: "etf_overlap", positions: [] }),
    ).toMatch(/한 개 이상/);
  });

  it("keeps SEC and sector requests limited to their contract fields", () => {
    expect(buildAdvisoryPayload(getAdvisoryFeature("sec_filing_risk"), { ticker: "aapl" })).toEqual(
      { analysis_type: "sec_filing_risk", ticker: "AAPL" },
    );
    expect(buildAdvisoryPayload(getAdvisoryFeature("sector_outlook"), {})).toEqual({
      analysis_type: "sector_outlook",
    });
  });
});
