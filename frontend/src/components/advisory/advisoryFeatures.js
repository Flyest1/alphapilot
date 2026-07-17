export const ADVISORY_FEATURES = [
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

export function buildAdvisoryPayload(feature, form) {
  const payload = { analysis_type: feature.id };
  if (feature.inputMode === "ticker") {
    return {
      ...payload,
      ticker: String(form.ticker || "")
        .trim()
        .toUpperCase(),
    };
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
    return tickers.length ? { ...payload, tickers, ...maxResults } : { ...payload, ...maxResults };
  }
  return payload;
}

export function validateAdvisoryPayload(feature, payload) {
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
  return "";
}
