import { describe, expect, it } from "vitest";

import { errorDetailMessage } from "../api/client.js";
import { isChunkLoadError } from "../components/ErrorBoundary.jsx";
import { blankNumericSettingFields } from "../pages/Settings.jsx";

describe("frontend guards", () => {
  it("joins FastAPI validation error messages", () => {
    expect(
      errorDetailMessage([
        { loc: ["body", "usd_krw_rate"], msg: "Input should be a valid number" },
        { msg: "Field required" },
      ]),
    ).toBe("Input should be a valid number / Field required");
    expect(errorDetailMessage({ message: "잠금", code: "locked" })).toBe("잠금");
    expect(errorDetailMessage("실패")).toBe("실패");
    expect(errorDetailMessage(undefined)).toBe("");
  });

  it("detects stale lazy chunks only", () => {
    expect(
      isChunkLoadError(new TypeError("Failed to fetch dynamically imported module: /a.js")),
    ).toBe(true);
    expect(isChunkLoadError(new Error("Cannot read properties of undefined"))).toBe(false);
  });

  it("flags cleared numeric settings instead of saving zero", () => {
    const settings = {
      stale_data_business_days: "",
      usd_krw_rate: 1400,
      target_domestic_pct: 40,
      target_global_pct: 40,
      target_cash_pct: 20,
      target_max_asset_pct: 25,
      rebalance_band_pct: 5,
      risk_per_trade_pct: 1,
      fee_rate_pct: 0,
      kr_tax_rate_pct: 0.18,
      fx_spread_pct: "abc",
    };
    expect(blankNumericSettingFields(settings)).toEqual([
      "stale_data_business_days",
      "fx_spread_pct",
    ]);
  });
});
