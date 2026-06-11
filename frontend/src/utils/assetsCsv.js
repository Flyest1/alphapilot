// 증권사/백업 CSV로 자산 일괄 등록·내보내기 (Phase 6-5)

export const CSV_COLUMNS = [
  "market",
  "ticker",
  "name",
  "quantity",
  "avg_price",
  "currency",
  "sector",
  "memo",
];

const HEADER_ALIASES = {
  market: ["market", "시장"],
  ticker: ["ticker", "티커", "종목코드"],
  name: ["name", "이름", "종목명"],
  quantity: ["quantity", "수량", "보유수량"],
  avg_price: ["avg_price", "평균단가", "평균매입가", "매입단가"],
  currency: ["currency", "통화"],
  sector: ["sector", "섹터", "업종"],
  memo: ["memo", "메모"],
};

const VALID_MARKETS = new Set(["KR", "US", "ETF", "CASH"]);

function escapeCell(value) {
  const text = String(value ?? "");
  if (/[",\n\r]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

export function assetsToCsv(assets = []) {
  const header = CSV_COLUMNS.join(",");
  const lines = assets.map((asset) =>
    CSV_COLUMNS.map((column) => escapeCell(asset[column])).join(","),
  );
  return [header, ...lines].join("\n");
}

// 따옴표/쉼표/줄바꿈을 처리하는 단순 CSV 파서
export function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = "";
  let inQuotes = false;
  const source = String(text || "").replace(/^\ufeff/, "");
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (inQuotes) {
      if (char === '"') {
        if (source[index + 1] === '"') {
          cell += '"';
          index += 1;
        } else {
          inQuotes = false;
        }
      } else {
        cell += char;
      }
      continue;
    }
    if (char === '"') {
      inQuotes = true;
    } else if (char === ",") {
      row.push(cell);
      cell = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && source[index + 1] === "\n") index += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += char;
    }
  }
  if (cell.length || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows.filter((cells) => cells.some((value) => String(value).trim() !== ""));
}

function resolveHeaderMap(headerCells) {
  const map = {};
  headerCells.forEach((cell, index) => {
    const normalized = String(cell || "")
      .trim()
      .toLowerCase();
    Object.entries(HEADER_ALIASES).forEach(([field, aliases]) => {
      if (aliases.includes(normalized)) map[field] = index;
    });
  });
  return map;
}

export function parseAssetsCsv(text) {
  const rows = parseCsv(text);
  if (!rows.length) {
    return { assets: [], errors: ["CSV 내용이 비어 있습니다."] };
  }
  const headerMap = resolveHeaderMap(rows[0]);
  const required = ["market", "ticker", "name", "quantity", "avg_price"];
  const missing = required.filter((field) => headerMap[field] == null);
  if (missing.length) {
    return {
      assets: [],
      errors: [
        `필수 헤더가 없습니다: ${missing.join(", ")} (지원 헤더: market/시장, ticker/티커/종목코드, name/종목명, quantity/수량, avg_price/평균단가)`,
      ],
    };
  }

  const assets = [];
  const errors = [];
  rows.slice(1).forEach((cells, rowIndex) => {
    const lineNumber = rowIndex + 2;
    const read = (field) => {
      const index = headerMap[field];
      return index == null ? "" : String(cells[index] ?? "").trim();
    };
    const market = read("market").toUpperCase();
    const ticker = read("ticker").toUpperCase();
    const name = read("name");
    const quantity = Number(read("quantity").replace(/,/g, ""));
    const avgPrice = Number(read("avg_price").replace(/,/g, ""));
    if (!VALID_MARKETS.has(market)) {
      errors.push(
        `${lineNumber}행: 시장은 KR/US/ETF/CASH 중 하나여야 합니다 (입력: ${market || "없음"})`,
      );
      return;
    }
    if (!ticker || !name) {
      errors.push(`${lineNumber}행: 티커와 이름은 필수입니다.`);
      return;
    }
    if (!Number.isFinite(quantity) || quantity < 0) {
      errors.push(`${lineNumber}행: 수량이 올바르지 않습니다.`);
      return;
    }
    if (!Number.isFinite(avgPrice) || avgPrice < 0) {
      errors.push(`${lineNumber}행: 평균 매입가가 올바르지 않습니다.`);
      return;
    }
    const currency =
      read("currency").toUpperCase() || (market === "KR" || market === "CASH" ? "KRW" : "USD");
    assets.push({
      market,
      ticker,
      name,
      quantity,
      avg_price: avgPrice,
      currency,
      sector: read("sector") || null,
      memo: read("memo") || null,
    });
  });
  return { assets, errors };
}
