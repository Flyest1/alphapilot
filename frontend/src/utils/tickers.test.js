import { describe, expect, it } from "vitest";

import { isKrTicker, isUsTicker } from "./tickers.js";

describe("ticker formats", () => {
  it("accepts KRX codes and US symbols", () => {
    expect(isKrTicker("005930")).toBe(true);
    expect(isKrTicker("0183J0")).toBe(true);
    expect(isKrTicker("AAPL")).toBe(false);
    expect(isUsTicker("BRK.B")).toBe(true);
    expect(isUsTicker("005930")).toBe(false);
    expect(isUsTicker("")).toBe(false);
  });
});
