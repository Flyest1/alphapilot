import { formatValue } from "../../utils/formatters.js";

const STATUS_LABELS = {
  available: "사용 가능",
  fresh: "최신",
  partial: "일부 제한",
  limited: "제한됨",
  "data-limited": "데이터 제한",
  insufficient_data: "근거 부족",
  unavailable: "이용 불가",
  relative_low_risk: "상대적 저위험",
  caution: "주의",
  high_risk: "고위험",
  BUY: "진입 후보",
  WATCH: "관찰",
  HOLD: "보유 검토",
  REDUCE: "비중 축소 검토",
  SELL: "매도 검토",
  verified_ai_beneficiary: "공시 근거 확인",
  ai_theme_caution: "테마 주의",
  fact: "사실",
  calculation: "계산",
  inference: "추론",
  limitation: "한계",
};

export const FIELD_LABELS = {
  disclaimer: "안내",
  summary: "요약",
  ticker: "티커",
  ticker_a: "ETF A",
  ticker_b: "ETF B",
  name: "종목명",
  company: "기업명",
  description: "설명",
  profile: "투자 성향",
  action: "의사결정 참고",
  analysis_status: "분석 상태",
  data_quality_status: "데이터 상태",
  investment_score: "투자 점수",
  investment_appeal_10: "매력도 (10점)",
  opportunity_score: "기회 점수",
  opportunity_status: "기회 상태",
  classification: "분류",
  risk_rating: "위험 등급",
  evaluation_status: "평가 상태",
  current_weight_pct: "현재 비중",
  suggested_weight_pct: "참고 비중",
  target_weight_pct: "목표 비중",
  weight_change_pct: "비중 변화",
  overlap_pct: "중복 비중",
  overlap_status: "중복 상태",
  minimum_confirmed_top10_overlap_pct: "확인된 상위 10개 중복",
  distribution_yield_pct: "분배수익률",
  trailing_twelve_month_distribution_yield_pct: "최근 12개월 분배수익률",
  expense_ratio_pct: "총보수",
  three_month_return_pct: "3개월 수익률",
  six_month_return_pct: "6개월 수익률",
  post_earnings_return_pct: "실적 발표 후 수익률",
  quarterly_revenue_growth_pct: "분기 매출 성장률",
  eps_change_pct: "EPS 변화율",
  eps_surprise_pct: "EPS 서프라이즈",
  operating_margin_pct: "영업이익률",
  operating_margin_change_pct_points: "영업이익률 변화",
  free_cash_flow_change_pct: "잉여현금흐름 변화율",
  debt_to_equity_pct: "부채/자본 비율",
  forward_pe: "예상 PER",
  trailing_pe: "PER",
  price_to_book: "PBR",
  enterprise_to_ebitda: "EV/EBITDA",
  market_cap_usd: "시가총액",
  overheating_risk_10: "과열 위험 (10점)",
  long_term_growth_10: "장기 성장성 (10점)",
  risk_category: "위험 범주",
  category: "범주",
  severity: "심각도",
  form: "서식",
  accession_number: "접수 번호",
  filed_at: "제출일",
  report_date: "보고 기간",
  filing_period: "공시 기준 기간",
  disclosure_delay_days: "공시 지연 일수",
  source_as_of: "근거 기준일",
  last_trading_date: "최근 거래일",
  provider: "제공처",
  status: "상태",
  rank: "순위",
  company_weight_pct: "기업 비중",
  holding_weight_pct: "편입 비중",
  sector: "섹터",
  proxy_ticker: "대표 ETF",
  return_1m_pct: "1개월 수익률",
  return_3m_pct: "3개월 수익률",
  return_6m_pct: "6개월 수익률",
  return_1y_pct: "1년 수익률",
  outlook_score: "전망 점수",
  severity_score: "위험 점수",
  new_or_emphasized: "신규·강조 여부",
  caution_reason: "주의 사유",
  excluded_tickers: "제외 ETF",
  weight_changes_vs_current_pct: "현재 대비 비중 변화",
  data_quality: "데이터 상태",
};

const PERCENT_FIELD = /(_pct|_percent|_percentage|_rate)$/;
const USD_FIELD = /(_usd|market_cap|\bcash\b)$/;
const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const ISO_TIMESTAMP_PATTERN = /^\d{4}-\d{2}-\d{2}T/;
const LIMITATION_STATUSES = new Set([
  "partial",
  "limited",
  "data-limited",
  "insufficient_data",
  "unavailable",
]);

const EVIDENCE_HOSTS = {
  sec_edgar: new Set(["data.sec.gov", "www.sec.gov"]),
  fred: new Set(["api.stlouisfed.org", "fred.stlouisfed.org"]),
  yfinance: new Set(["finance.yahoo.com", "query1.finance.yahoo.com", "query2.finance.yahoo.com"]),
  gdelt: new Set(["api.gdeltproject.org"]),
};

export const RESULT_CONFIG = {
  undervalued_us_stocks: {
    title: "미국 저평가 후보",
    sections: [
      {
        key: "top_candidates",
        title: "우선 검토 후보",
        sort: "investment_score",
        fields: [
          "ticker",
          "name",
          "investment_score",
          "investment_appeal_10",
          "trailing_pe",
          "forward_pe",
          "quarterly_revenue_growth_pct",
          "action",
          "analysis_status",
        ],
      },
      {
        key: "rows",
        title: "전체 스크리닝",
        sort: "investment_score",
        fields: [
          "ticker",
          "investment_score",
          "three_month_return_pct",
          "quarterly_revenue_growth_pct",
          "free_cash_flow_change_pct",
          "debt_to_equity_pct",
          "action",
          "analysis_status",
        ],
      },
    ],
  },
  etf_rebalancing: {
    title: "ETF 리밸런싱 참고",
    sections: [
      {
        key: "etfs",
        title: "보유 ETF 점검",
        sort: "current_weight_pct",
        fields: [
          "ticker",
          "name",
          "current_weight_pct",
          "target_weight_pct",
          "expense_ratio_pct",
          "analysis_status",
          "data_quality",
        ],
      },
      {
        key: "top10_overlap",
        title: "상위 10개 편입 종목 중복",
        sort: "minimum_confirmed_top10_overlap_pct",
        fields: ["ticker_a", "ticker_b", "minimum_confirmed_top10_overlap_pct", "status"],
      },
      {
        key: "scenarios",
        title: "참고 시나리오",
        fields: [
          "name",
          "description",
          "weight_changes_vs_current_pct",
          "excluded_tickers",
          "status",
        ],
      },
    ],
  },
  post_earnings_opportunities: {
    title: "실적 발표 후 관찰 후보",
    sections: [
      {
        key: "rankings",
        title: "우선순위",
        sort: "opportunity_score",
        fields: [
          "ticker",
          "name",
          "opportunity_score",
          "post_earnings_return_pct",
          "eps_surprise_pct",
          "quarterly_revenue_growth_pct",
          "action",
          "analysis_status",
        ],
      },
      {
        key: "rows",
        title: "실적·가격 반응",
        sort: "opportunity_score",
        fields: [
          "ticker",
          "earnings_release_date",
          "post_earnings_return_pct",
          "eps_change_pct",
          "operating_margin_change_pct_points",
          "interest_price_range",
          "analysis_status",
        ],
      },
    ],
  },
  ai_beneficiaries: {
    title: "AI 수혜 근거 점검",
    sections: [
      {
        key: "verified_ai_beneficiaries",
        title: "공시 근거가 확인된 후보",
        sort: "investment_appeal_10",
        fields: [
          "ticker",
          "name",
          "investment_appeal_10",
          "long_term_growth_10",
          "overheating_risk_10",
          "classification",
          "analysis_status",
        ],
      },
      {
        key: "ai_theme_caution",
        title: "테마 주의 목록",
        sort: "overheating_risk_10",
        fields: ["ticker", "name", "overheating_risk_10", "classification", "analysis_status"],
      },
      {
        key: "rows",
        title: "전체 확인 결과",
        sort: "investment_appeal_10",
        fields: [
          "ticker",
          "classification",
          "quantitative_evidence_count",
          "disclosure_count",
          "forward_pe",
          "six_month_return_pct",
          "analysis_status",
        ],
      },
    ],
  },
  high_dividend_etfs: {
    title: "고배당 ETF 비교",
    sections: [
      {
        key: "relatively_stable_etfs",
        title: "상대적 안정성 참고",
        sort: "distribution_yield_pct",
        fields: [
          "ticker",
          "name",
          "distribution_yield_pct",
          "expense_ratio_pct",
          "risk_rating",
          "analysis_status",
        ],
      },
      {
        key: "etfs",
        title: "전체 ETF",
        sort: "distribution_yield_pct",
        fields: [
          "ticker",
          "name",
          "distribution_yield_pct",
          "expense_ratio_pct",
          "return_1y_pct",
          "analysis_status",
        ],
      },
      {
        key: "caution_etfs",
        title: "주의 ETF",
        fields: [
          "ticker",
          "name",
          "distribution_yield_pct",
          "risk_rating",
          "caution_reason",
          "analysis_status",
        ],
      },
    ],
  },
  sec_filing_risk: {
    title: "SEC 공시 위험 점검",
    sections: [
      {
        key: "risk_categories",
        title: "위험 범주",
        sort: "severity_score",
        fields: [
          "risk_category",
          "category",
          "severity",
          "severity_score",
          "new_or_emphasized",
          "summary",
        ],
      },
      {
        key: "management_caution_signals",
        title: "경영진 주의 신호",
        fields: ["category", "summary", "source_as_of"],
      },
      {
        key: "newly_emphasized_risks",
        title: "새롭게 강조된 위험",
        fields: ["category", "summary", "source_as_of"],
      },
    ],
  },
  etf_overlap: {
    title: "ETF 중복·분산 점검",
    sections: [
      {
        key: "pairwise_overlap",
        title: "ETF 쌍별 중복",
        sort: "overlap_pct",
        fields: ["ticker_a", "ticker_b", "overlap_pct", "overlap_status", "data_quality"],
      },
      {
        key: "actual_company_exposure",
        title: "실제 기업 노출",
        sort: "company_weight_pct",
        fields: ["ticker", "company", "company_weight_pct", "holding_weight_pct", "sector"],
      },
      {
        key: "rebalancing_plans",
        title: "분산 참고 시나리오",
        fields: ["name", "description", "target_weight_pct", "excluded_tickers", "status"],
      },
      {
        key: "target_weight_scenarios",
        title: "목표 비중 참고",
        fields: ["name", "description", "target_weight_pct", "status"],
      },
    ],
  },
  sector_outlook: {
    title: "섹터 전망 참고",
    sections: [
      {
        key: "sectors",
        title: "섹터 비교",
        sort: "outlook_score",
        fields: [
          "sector",
          "proxy_ticker",
          "outlook_score",
          "return_1m_pct",
          "return_3m_pct",
          "return_6m_pct",
          "analysis_status",
        ],
      },
      {
        key: "investor_portfolios",
        title: "투자 성향별 참고",
        fields: ["name", "profile", "description", "sectors", "status"],
      },
    ],
  },
};

export function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function safeRows(value) {
  return Array.isArray(value) ? value.filter(isRecord) : [];
}

export function labelFor(key) {
  return FIELD_LABELS[key] || String(key || "").replace(/_/g, " ");
}

export function statusLabel(value) {
  return STATUS_LABELS[value] || String(value ?? "-");
}

export function formatAdvisoryDate(value) {
  if (typeof value !== "string") return String(value ?? "-");
  if (ISO_DATE_PATTERN.test(value)) {
    const [year, month, day] = value.split("-").map(Number);
    return `${year}년 ${month}월 ${day}일`;
  }
  if (!ISO_TIMESTAMP_PATTERN.test(value)) return value;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(date);
}

export function formatAdvisoryValue(key, value) {
  if (value == null || value === "") return "-";
  if (typeof value === "boolean") return value ? "예" : "아니오";
  if (typeof value === "number") {
    if (PERCENT_FIELD.test(key)) return `${formatValue(value)}%`;
    if (USD_FIELD.test(key)) return `$${formatValue(value)}`;
    return formatValue(value);
  }
  if (Array.isArray(value)) return value.map((item) => formatAdvisoryValue(key, item)).join(", ");
  if (isRecord(value))
    return Object.entries(value)
      .map(([itemKey, item]) => `${labelFor(itemKey)}: ${formatAdvisoryValue(itemKey, item)}`)
      .join(" · ");
  if (
    typeof value === "string" &&
    (ISO_DATE_PATTERN.test(value) || ISO_TIMESTAMP_PATTERN.test(value))
  ) {
    return formatAdvisoryDate(value);
  }
  return STATUS_LABELS[value] || String(value);
}

export function sortRows(rows, field) {
  if (!field) return rows;
  return [...rows].sort((left, right) => {
    const leftValue = Number(left?.[field]);
    const rightValue = Number(right?.[field]);
    if (Number.isFinite(leftValue) && Number.isFinite(rightValue)) return rightValue - leftValue;
    if (Number.isFinite(leftValue)) return -1;
    if (Number.isFinite(rightValue)) return 1;
    return String(left?.ticker || left?.name || "").localeCompare(
      String(right?.ticker || right?.name || ""),
    );
  });
}

export function visibleFields(rows, requestedFields) {
  const configured = requestedFields.filter((field) => rows.some((row) => row[field] != null));
  if (configured.length) return configured;
  return [...new Set(rows.flatMap((row) => Object.keys(row)))].slice(0, 8);
}

export function limitedStatuses(result) {
  const candidates = [
    result?.data_quality?.status,
    result?.evaluation_status,
    result?.analysis_status,
  ];
  const rootStatuses = candidates.filter((status) => LIMITATION_STATUSES.has(status));
  if (rootStatuses.length) return [...new Set(rootStatuses)];
  if (candidates.some((status) => status === "available" || status === "fresh")) return [];

  const statuses = new Set();
  Object.values(result || {}).forEach((value) => {
    safeRows(value).forEach((row) => {
      [row.analysis_status, row.data_quality_status, row.data_quality?.status].forEach((status) => {
        if (LIMITATION_STATUSES.has(status)) statuses.add(status);
      });
    });
  });
  return [...statuses];
}

export function archivesUrl(filing) {
  const url = filing?.url || filing?.source_url || filing?.filing_url || filing?.archives_url;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" &&
      parsed.hostname === "www.sec.gov" &&
      parsed.pathname.startsWith("/Archives/")
      ? url
      : "";
  } catch {
    return "";
  }
}

function evidenceProviderGroup(provider) {
  const normalized = String(provider || "")
    .trim()
    .toLowerCase();
  if (normalized.startsWith("sec_edgar")) return "sec_edgar";
  if (normalized.startsWith("fred")) return "fred";
  if (normalized.startsWith("yfinance")) return "yfinance";
  if (normalized.startsWith("gdelt")) return "gdelt";
  return "";
}

export function evidenceUrl(evidence) {
  const providerGroup = evidenceProviderGroup(evidence?.provider);
  const allowedHosts = EVIDENCE_HOSTS[providerGroup];
  if (!allowedHosts) return "";
  try {
    const parsed = new URL(evidence?.url);
    if (
      parsed.protocol !== "https:" ||
      parsed.username ||
      parsed.password ||
      (parsed.port && parsed.port !== "443")
    ) {
      return "";
    }
    return allowedHosts.has(parsed.hostname.toLowerCase()) ? parsed.href : "";
  } catch {
    return "";
  }
}

function nestedRecords(value, depth = 0, records = [], seen = new Set()) {
  if (depth > 5 || records.length >= 200 || value == null || typeof value !== "object") {
    return records;
  }
  if (seen.has(value)) return records;
  seen.add(value);
  if (Array.isArray(value)) {
    value.forEach((item) => nestedRecords(item, depth + 1, records, seen));
    return records;
  }
  records.push(value);
  Object.values(value).forEach((item) => nestedRecords(item, depth + 1, records, seen));
  return records;
}

function filingPeriodFromContext(context) {
  if (!Array.isArray(context?.filings)) return null;
  const periods = context.filings
    .filter(isRecord)
    .map(
      (filing) =>
        filing.report_date ||
        filing.filing_date ||
        filing.filing_period ||
        filing.period_of_report ||
        filing.filed_at,
    )
    .filter(Boolean)
    .map(String)
    .sort();
  return periods.at(-1) || null;
}

export function nportDisclosure(result) {
  const records = nestedRecords(result);
  const nportRow = records.find((row) => {
    const normalizedProvider = String(row.provider || "")
      .toLowerCase()
      .replace(/[^a-z0-9]/g, "");
    const form = String(row.form || "").toUpperCase();
    const hasDelayedFilingContext =
      row.filing_period &&
      (row.public_data_delay_days != null || row.disclosure_delay_days != null);
    return (
      normalizedProvider.includes("nport") || form.includes("N-PORT") || hasDelayedFilingContext
    );
  });
  if (!nportRow) return null;
  return {
    filingPeriod:
      nportRow.filing_period ||
      nportRow.report_date ||
      nportRow.filing_date ||
      filingPeriodFromContext(nportRow) ||
      nportRow.source_as_of,
    delay: nportRow.public_data_delay_days ?? nportRow.disclosure_delay_days,
  };
}
