export const ADVISORY_FEATURES = [
  {
    id: "profit_taking_review",
    title: "이익실현 판단",
    description: "수익 중인 보유 자산의 이익 보존·보유·추가 노출 조건을 독립적으로 점검합니다.",
    inputMode: "owned_asset",
    details: ["최종 의견", "핵심 이유", "이익실현·보유 비교", "리포트 충돌", "재검토 조건"],
  },
  {
    id: "undervalued_us_stocks",
    title: "저평가 미국 주식",
    description: "실적·밸류에이션·가이던스와 하방 위험을 함께 비교합니다.",
    inputMode: "tickers",
    defaultUniverse: "current_global_candidates",
    details: ["최근 3개월", "분기 재무", "가이던스", "밸류", "리스크", "상위 5개"],
  },
  {
    id: "etf_rebalancing",
    title: "ETF 리밸런싱",
    description: "보유 ETF 비중을 기준으로 성과·위험과 세 가지 성향 조합을 검토합니다.",
    inputMode: "positions",
    details: ["1년·3년", "변동성", "배당", "보유 종목", "섹터", "중복", "민감도", "공격·균형·안정"],
  },
  {
    id: "post_earnings_opportunities",
    title: "실적 발표 후 기회",
    description: "최근 실적 발표 뒤 조정된 종목의 회복 조건과 가격대를 살펴봅니다.",
    inputMode: "tickers",
    defaultUniverse: "current_global_candidates",
    details: ["실적 후 하락", "매출", "EPS", "마진", "가이던스", "경영진", "가격대", "상위 5개"],
  },
  {
    id: "ai_beneficiaries",
    title: "AI 수혜주",
    description: "AI 수혜의 근거와 과열 위험을 분리해 후보를 점검합니다.",
    inputMode: "tickers",
    defaultUniverse: "current_global_candidates",
    details: ["진짜 수혜 10개", "주의 5개", "3개 점수"],
  },
  {
    id: "high_dividend_etfs",
    title: "고배당 ETF",
    description: "분배금만 보지 않고 지속성·변동성·구성 위험을 비교합니다.",
    inputMode: "tickers",
    defaultUniverse: "current_global_candidates",
    details: ["피해야 할 상품", "주의 5개", "상대 안정 5개"],
  },
  {
    id: "sec_filing_risk",
    title: "SEC 공시 위험",
    description: "지정 종목의 공시에서 위험 신호와 상대 위험 수준을 확인합니다.",
    inputMode: "ticker",
    details: ["10-K", "10-Q", "8-K", "상대 저위험·주의·고위험"],
  },
  {
    id: "etf_overlap",
    title: "ETF 중복 분석",
    description: "보유 ETF 구성의 중복 노출과 대체 리밸런싱 안을 분석합니다.",
    inputMode: "positions",
    details: ["상위 10개 종목", "중복", "섹터", "스타일", "리밸런싱 3안"],
  },
  {
    id: "sector_outlook",
    title: "섹터 전망",
    description: "지정된 10개 섹터의 환경과 투자자 성향별 조합을 비교합니다.",
    inputMode: "none",
    details: ["10개 섹터", "투자자 조합 3개"],
  },
];

export function getAdvisoryFeature(analysisType) {
  return ADVISORY_FEATURES.find((feature) => feature.id === analysisType) || ADVISORY_FEATURES[0];
}

export function parseTickers(value) {
  return [
    ...new Set(
      String(value || "")
        .toUpperCase()
        .split(/[\s,]+/)
        .filter(Boolean),
    ),
  ];
}

function optionalNumber(value) {
  const normalized = String(value ?? "").trim();
  return normalized === "" ? undefined : Number(normalized);
}

function parseThemes(value) {
  return [
    ...new Set(
      String(value || "")
        .split(/[\n,]+/)
        .map((theme) => theme.trim())
        .filter(Boolean),
    ),
  ];
}

function customProxies(rows) {
  return Object.fromEntries(
    (rows || [])
      .map((row) => [
        String(row.sector || "").trim(),
        String(row.ticker || "")
          .trim()
          .toUpperCase(),
      ])
      .filter(([sector, ticker]) => sector && ticker),
  );
}

export function buildAdvisoryPayload(feature, form) {
  const payload = { analysis_type: feature.id };
  if (feature.inputMode === "owned_asset") {
    return {
      ...payload,
      asset_id: String(form.asset_id || "").trim(),
      review_horizon: form.review_horizon || "medium",
    };
  }
  if (feature.inputMode === "ticker") {
    const payloadWithTicker = {
      ...payload,
      ticker: String(form.ticker || "")
        .trim()
        .toUpperCase(),
    };
    const lookbackDays = optionalNumber(form.lookback_days);
    return lookbackDays === undefined
      ? payloadWithTicker
      : { ...payloadWithTicker, lookback_days: lookbackDays };
  }
  if (feature.inputMode === "positions") {
    return {
      ...payload,
      positions: (form.positions || [])
        .map((position) => {
          const rawWeight = String(position.weight_pct ?? "").trim();
          return {
            ticker: String(position.ticker || "")
              .trim()
              .toUpperCase(),
            weight_pct: rawWeight === "" ? null : Number(rawWeight),
          };
        })
        .filter((position) => position.ticker),
    };
  }
  if (feature.inputMode === "tickers") {
    const tickers = parseTickers(form.tickers);
    const maxResults = ["undervalued_us_stocks", "post_earnings_opportunities"].includes(feature.id)
      ? { max_results: 5 }
      : {};
    const tickerPayload = tickers.length
      ? { ...payload, tickers, ...maxResults }
      : { ...payload, ...maxResults };
    if (feature.id === "undervalued_us_stocks") {
      const minMarketCap = optionalNumber(form.min_market_cap_usd);
      return minMarketCap === undefined
        ? tickerPayload
        : { ...tickerPayload, min_market_cap_usd: minMarketCap };
    }
    if (feature.id === "post_earnings_opportunities") {
      const lookbackDays = optionalNumber(form.lookback_days);
      return lookbackDays === undefined
        ? tickerPayload
        : { ...tickerPayload, lookback_days: lookbackDays };
    }
    if (feature.id === "ai_beneficiaries") {
      const themes = parseThemes(form.themes);
      return themes.length ? { ...tickerPayload, themes } : tickerPayload;
    }
    if (feature.id === "high_dividend_etfs") {
      const minDistributionYield = optionalNumber(form.min_distribution_yield_percent);
      return minDistributionYield === undefined
        ? tickerPayload
        : { ...tickerPayload, min_distribution_yield_percent: minDistributionYield };
    }
    return tickerPayload;
  }
  if (feature.id === "sector_outlook") {
    const proxies = customProxies(form.customProxies);
    return Object.keys(proxies).length ? { ...payload, custom_proxies: proxies } : payload;
  }
  return payload;
}

export function validateAdvisoryPayload(feature, payload, form = {}) {
  if (feature.inputMode === "owned_asset") {
    if (!payload.asset_id) return "이익실현 판단을 위해 보유 자산을 선택하세요.";
    if (!["short", "medium", "long"].includes(payload.review_horizon)) {
      return "검토 기간은 단기, 중기, 장기 중에서 선택하세요.";
    }
  }
  if (feature.inputMode === "ticker" && !payload.ticker) {
    return "SEC 공시 위험 분석에는 티커를 입력하세요.";
  }
  if (feature.inputMode === "positions") {
    if (feature.id === "etf_overlap" && !payload.positions.length) {
      return "중복 분석할 ETF 티커를 한 개 이상 입력하세요.";
    }
    if (
      payload.positions.some(
        (position) => position.weight_pct != null && !Number.isFinite(position.weight_pct),
      )
    ) {
      return "ETF 비중은 숫자로 입력하세요.";
    }
  }
  if (feature.id === "undervalued_us_stocks") {
    const value = payload.min_market_cap_usd;
    if (value !== undefined && (!Number.isInteger(value) || value < 0)) {
      return "최소 시가총액은 0 이상의 정수(USD)로 입력해 주세요.";
    }
  }
  if (feature.id === "post_earnings_opportunities") {
    const value = payload.lookback_days;
    if (value !== undefined && (!Number.isInteger(value) || value < 1 || value > 90)) {
      return "실적 발표 조회 기간은 1~90일 사이의 정수로 입력해 주세요.";
    }
  }
  if (feature.id === "sec_filing_risk") {
    const value = payload.lookback_days;
    if (value !== undefined && (!Number.isInteger(value) || value < 1 || value > 365)) {
      return "SEC 공시 조회 기간은 1~365일 사이의 정수로 입력해 주세요.";
    }
  }
  if (feature.id === "ai_beneficiaries" && payload.themes?.length > 20) {
    return "AI 테마는 최대 20개까지 입력할 수 있습니다.";
  }
  if (feature.id === "high_dividend_etfs") {
    const value = payload.min_distribution_yield_percent;
    if (value !== undefined && (!Number.isFinite(value) || value < 0 || value > 100)) {
      return "최소 분배수익률은 0~100% 사이의 숫자로 입력해 주세요.";
    }
  }
  if (feature.id === "sector_outlook") {
    const hasIncompleteProxy = (form.customProxies || []).some((row) => {
      const sector = String(row.sector || "").trim();
      const ticker = String(row.ticker || "").trim();
      return Boolean(sector) !== Boolean(ticker);
    });
    if (hasIncompleteProxy) {
      return "사용자 지정 프록시는 섹터명과 ETF 티커를 모두 입력해 주세요.";
    }
  }
  return "";
}
