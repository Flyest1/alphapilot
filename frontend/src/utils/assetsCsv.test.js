import { describe, expect, it } from "vitest";

import { assetsToCsv, parseAssetsCsv, parseCsv } from "./assetsCsv.js";

describe("assetsToCsv", () => {
  it("serializes assets with header and escapes special characters", () => {
    const csv = assetsToCsv([
      {
        market: "KR",
        ticker: "005930",
        name: "삼성전자",
        quantity: 10,
        avg_price: 70000,
        currency: "KRW",
        sector: "Technology",
        memo: '메모, "특수"',
      },
    ]);
    const lines = csv.split("\n");

    expect(lines[0]).toBe("market,ticker,name,quantity,avg_price,currency,sector,memo");
    expect(lines[1]).toContain("005930");
    expect(lines[1]).toContain('"메모, ""특수"""');
  });
});

describe("parseCsv", () => {
  it("handles quoted cells with commas and newlines", () => {
    const rows = parseCsv('a,"b,1","c\n2"\r\nd,e,f');

    expect(rows).toEqual([
      ["a", "b,1", "c\n2"],
      ["d", "e", "f"],
    ]);
  });
});

describe("parseAssetsCsv", () => {
  it("parses rows with korean header aliases and fills default currency", () => {
    const csv = [
      "시장,종목코드,종목명,수량,평균단가",
      "KR,005930,삼성전자,10,70000",
      "US,AAPL,Apple,2,180.5",
    ].join("\n");

    const { assets, errors } = parseAssetsCsv(csv);

    expect(errors).toEqual([]);
    expect(assets).toHaveLength(2);
    expect(assets[0]).toMatchObject({
      market: "KR",
      ticker: "005930",
      quantity: 10,
      avg_price: 70000,
      currency: "KRW",
    });
    expect(assets[1].currency).toBe("USD");
  });

  it("collects row-level errors and keeps valid rows", () => {
    const csv = [
      "market,ticker,name,quantity,avg_price",
      "XX,BAD,잘못된 시장,1,100",
      "KR,005930,삼성전자,abc,100",
      "KR,069500,KODEX 200,5,30000",
    ].join("\n");

    const { assets, errors } = parseAssetsCsv(csv);

    expect(assets).toHaveLength(1);
    expect(assets[0].ticker).toBe("069500");
    expect(errors).toHaveLength(2);
    expect(errors[0]).toContain("2행");
  });

  it("fails clearly when required headers are missing", () => {
    const { assets, errors } = parseAssetsCsv("ticker,name\nAAPL,Apple");

    expect(assets).toEqual([]);
    expect(errors[0]).toContain("필수 헤더");
  });
});
