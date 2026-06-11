import { describe, expect, it } from "vitest";

import { average, formatMoney, formatPercent, formatReturn, formatValue } from "./formatters.js";

describe("formatValue", () => {
  it("formats numbers with thousand separators", () => {
    expect(formatValue(1234567.891)).toBe("1,234,567.89");
  });

  it("returns dash for null or undefined", () => {
    expect(formatValue(null)).toBe("-");
    expect(formatValue(undefined)).toBe("-");
  });

  it("returns the raw value when not numeric", () => {
    expect(formatValue("KRW")).toBe("KRW");
  });
});

describe("formatReturn", () => {
  it("formats numeric returns with two decimals and percent", () => {
    expect(formatReturn(3.14159)).toBe("3.14%");
    expect(formatReturn(-2)).toBe("-2.00%");
  });

  it("returns dash for null or non-numeric values", () => {
    expect(formatReturn(null)).toBe("-");
    expect(formatReturn("abc")).toBe("-");
  });
});

describe("formatPercent", () => {
  it("formats finite numbers", () => {
    expect(formatPercent("12.345")).toBe("12.35%");
  });

  it("returns dash for non-finite values", () => {
    expect(formatPercent(undefined)).toBe("-");
  });
});

describe("formatMoney", () => {
  it("treats null as zero", () => {
    expect(formatMoney(null)).toBe("0");
  });

  it("formats large values", () => {
    expect(formatMoney(1500000)).toBe("1,500,000");
  });
});

describe("average", () => {
  it("averages numeric values and ignores non-numeric entries", () => {
    expect(average([1, 2, 3, null, "x"])).toBe(2);
  });

  it("returns null when nothing is numeric", () => {
    expect(average([null, undefined])).toBeNull();
  });
});
