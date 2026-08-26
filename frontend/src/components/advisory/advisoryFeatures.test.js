import { describe, expect, it } from "vitest";

import {
  ADVISORY_FEATURES,
  buildAdvisoryPayload,
  getAdvisoryFeature,
  validateAdvisoryPayload,
} from "./advisoryFeatures.js";

describe("advisory payloads", () => {
  it("defines all ten advisory analyses", () => {
    expect(ADVISORY_FEATURES).toHaveLength(10);
    expect(ADVISORY_FEATURES.map((feature) => feature.id)).toEqual([
      "profit_taking_review",
      "undervalued_us_stocks",
      "high_upside_speculative_stocks",
      "etf_rebalancing",
      "post_earnings_opportunities",
      "ai_beneficiaries",
      "high_dividend_etfs",
      "sec_filing_risk",
      "etf_overlap",
      "sector_outlook",
    ]);
  });

  it("builds only the stored-asset profit-taking request contract", () => {
    const feature = getAdvisoryFeature("profit_taking_review");
    const payload = buildAdvisoryPayload(feature, {
      asset_id: "asset-123",
      review_horizon: "medium",
      avg_price: "100",
      current_price: "120",
      return_rate: "20",
    });

    expect(payload).toEqual({
      analysis_type: "profit_taking_review",
      asset_id: "asset-123",
      review_horizon: "medium",
    });
    expect(validateAdvisoryPayload(feature, payload)).toBe("");
    expect(
      validateAdvisoryPayload(feature, { analysis_type: "profit_taking_review", asset_id: "" }),
    ).toMatch(/보유 자산/);
    expect(
      validateAdvisoryPayload(feature, {
        analysis_type: "profit_taking_review",
        asset_id: "asset-123",
        review_horizon: "invalid",
      }),
    ).toMatch(/단기, 중기, 장기/);
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

  it("builds a bounded speculative stock discovery request", () => {
    const feature = getAdvisoryFeature("high_upside_speculative_stocks");

    expect(buildAdvisoryPayload(feature, { tickers: "biox, rxrx" })).toEqual({
      analysis_type: "high_upside_speculative_stocks",
      tickers: ["BIOX", "RXRX"],
      max_results: 5,
    });
    expect(buildAdvisoryPayload(feature, { tickers: "" })).toEqual({
      analysis_type: "high_upside_speculative_stocks",
      max_results: 5,
    });
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

  it("adds advanced request fields only when the user supplies them", () => {
    expect(
      buildAdvisoryPayload(getAdvisoryFeature("undervalued_us_stocks"), {
        tickers: "aapl",
        min_market_cap_usd: "10000000000",
      }),
    ).toEqual({
      analysis_type: "undervalued_us_stocks",
      tickers: ["AAPL"],
      max_results: 5,
      min_market_cap_usd: 10000000000,
    });
    expect(
      buildAdvisoryPayload(getAdvisoryFeature("post_earnings_opportunities"), {
        tickers: "msft",
        lookback_days: "30",
      }),
    ).toMatchObject({ lookback_days: 30 });
    expect(
      buildAdvisoryPayload(getAdvisoryFeature("sec_filing_risk"), {
        ticker: "aapl",
        lookback_days: "120",
      }),
    ).toEqual({
      analysis_type: "sec_filing_risk",
      ticker: "AAPL",
      lookback_days: 120,
    });
    expect(
      buildAdvisoryPayload(getAdvisoryFeature("ai_beneficiaries"), {
        tickers: "nvda",
        themes: "반도체, 데이터센터\n전력 인프라",
      }),
    ).toMatchObject({ themes: ["반도체", "데이터센터", "전력 인프라"] });
    expect(
      buildAdvisoryPayload(getAdvisoryFeature("high_dividend_etfs"), {
        tickers: "schd",
        min_distribution_yield_percent: "3.5",
      }),
    ).toMatchObject({ min_distribution_yield_percent: 3.5 });
    expect(
      buildAdvisoryPayload(getAdvisoryFeature("sector_outlook"), {
        customProxies: [
          { sector: "반도체", ticker: "soxx" },
          { sector: "", ticker: "" },
        ],
      }),
    ).toEqual({ analysis_type: "sector_outlook", custom_proxies: { 반도체: "SOXX" } });
  });

  it("validates advanced request field boundaries", () => {
    expect(
      validateAdvisoryPayload(getAdvisoryFeature("post_earnings_opportunities"), {
        analysis_type: "post_earnings_opportunities",
        max_results: 5,
        lookback_days: 91,
      }),
    ).toMatch(/1~90일/);
    expect(
      validateAdvisoryPayload(getAdvisoryFeature("high_dividend_etfs"), {
        analysis_type: "high_dividend_etfs",
        min_distribution_yield_percent: 101,
      }),
    ).toMatch(/0~100%/);
    expect(
      validateAdvisoryPayload(
        getAdvisoryFeature("sector_outlook"),
        { analysis_type: "sector_outlook" },
        { customProxies: [{ sector: "반도체", ticker: "" }] },
      ),
    ).toMatch(/모두 입력/);
  });
});
