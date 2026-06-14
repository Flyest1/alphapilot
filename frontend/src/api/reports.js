export function strategyCount(report) {
  return report?.content?.asset_strategies?.length || 0;
}

export function dataLimitedCount(report) {
  return (
    report?.content?.asset_strategies?.filter((strategy) => strategy.reasoning === "data-limited")
      .length || 0
  );
}

export function normalizeTicker(ticker) {
  return String(ticker || "")
    .toUpperCase()
    .replace(/\.KS$|\.KQ$/, "")
    .trim();
}

export function splitStrategiesByAssets(strategies = [], assets = []) {
  const ownedTickers = new Set(assets.map((asset) => normalizeTicker(asset.ticker)));
  return {
    ownedStrategies: strategies.filter((strategy) =>
      ownedTickers.has(normalizeTicker(strategy.ticker)),
    ),
    candidateStrategies: strategies.filter(
      (strategy) => !ownedTickers.has(normalizeTicker(strategy.ticker)),
    ),
  };
}

export function isTechnicalOnlyReport(report) {
  return (
    report?.content?.key_risks?.includes("AI reasoning unavailable for this report") ||
    report?.content?.asset_strategies?.some((strategy) =>
      strategy.reasoning?.includes("technical-only fallback"),
    ) ||
    false
  );
}

export function pickReportWithStrategies(latestReports = {}) {
  const source = latestReports || {};
  const reports = [source.domestic, source.global].filter(Boolean);
  return reports.find((report) => strategyCount(report) > 0) || reports[0] || null;
}

export function reportTypeLabel(reportType) {
  return reportType === "domestic" ? "국내" : "글로벌";
}

export function reportTitle(report) {
  if (!report) return "선택된 리포트가 없습니다.";
  return `${reportTypeLabel(report.report_type)} 시장 리포트`;
}

export function formatReportTime(value) {
  if (!value) return "생성 전";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export const ACTION_LABELS = {
  BUY: "매수",
  HOLD: "보유",
  REDUCE: "축소",
  SELL: "매도",
  WATCH: "관찰",
};

export function actionLabel(action) {
  return ACTION_LABELS[action] || action;
}

export function formatStrategyMessageValue(value) {
  if (value == null) return "";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "";
  return numeric.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function strategyTitle(strategy) {
  const ticker = String(strategy.ticker || "").trim();
  const name = String(strategy.name || "").trim();
  const tickerText = ticker ? `(${ticker})` : "";
  const displayName = name && name !== ticker ? name : "";

  return [actionLabel(strategy.action), tickerText, displayName].filter(Boolean).join(" ");
}

function formatStrategyRange(low, current, high) {
  const lowText = formatStrategyMessageValue(low);
  const currentText = formatStrategyMessageValue(current);
  const highText = formatStrategyMessageValue(high);
  const parts = [lowText, currentText, highText].filter(Boolean);
  if (parts.length >= 2) return parts.join("~");
  return parts[0] || "";
}

export function importantStrategyMessages(strategies = [], limit = 8) {
  const priority = { BUY: 0, SELL: 1, REDUCE: 2, WATCH: 3, HOLD: 4 };
  return [...strategies]
    .filter((strategy) => strategy.reasoning !== "data-limited")
    .sort(
      (a, b) =>
        (priority[a.action] ?? 9) - (priority[b.action] ?? 9) ||
        Number(b.confidence || 0) - Number(a.confidence || 0),
    )
    .slice(0, limit)
    .map((strategy) => {
      const buyRange = formatStrategyRange(
        strategy.buy_range_low,
        strategy.current_price,
        strategy.buy_range_high,
      );
      const target = formatStrategyMessageValue(strategy.target_price);
      const stop = formatStrategyMessageValue(strategy.stop_loss);
      const confidence =
        strategy.confidence == null || strategy.confidence === ""
          ? ""
          : `신뢰도 ${strategy.confidence}%`;
      const rangeLine = buyRange ? `매수구간 ${buyRange}` : "";
      const exitLine = [
        target ? `목표 ${target}` : "",
        stop ? `손절 ${stop}` : "",
        confidence,
      ].filter(Boolean);

      return {
        key: `${strategy.ticker}-${strategy.action}-${strategy.confidence}-${strategy.name || ""}`,
        text: strategyTitle(strategy),
        rangeLine,
        exitLine: exitLine.join(", "),
        details: [rangeLine, exitLine.join(", ")].filter(Boolean).join(" · "),
        action: strategy.action,
        strategy,
      };
    });
}

export function reportAiModeLabel(report) {
  if (!report) return "-";
  return isTechnicalOnlyReport(report) ? "기술 지표만" : "AI";
}

const TEXT_REPLACEMENTS = new Map([
  ["data-limited", "데이터 제한"],
  [
    "technical-only fallback (LLM unavailable)",
    "AI 추론을 사용할 수 없어 기술 지표 기반으로 생성했습니다.",
  ],
  [
    "AI reasoning unavailable for this report",
    "AI 추론을 사용할 수 없어 기술 지표 기반으로 생성했습니다.",
  ],
  ["cash reserve; no market data fetch", "현금성 자산이라 시장 데이터 조회를 건너뜁니다."],
  [
    "cash allocation can reduce upside participation",
    "현금 비중은 하락 위험을 낮출 수 있지만 상승 참여를 제한할 수 있습니다.",
  ],
  ["cash allocation target changes", "현금 비중 목표가 바뀌면 전략을 다시 검토합니다."],
  ["market data is stale or unavailable", "시장 데이터가 지연되었거나 사용할 수 없습니다."],
  ["fresh market data becomes available", "최신 시장 데이터가 확보되면 다시 판단합니다."],
  [
    "technical score recovers above 50 with improving momentum",
    "기술 점수가 50을 회복하고 모멘텀이 개선되면 판단을 다시 검토합니다.",
  ],
]);

const TREND_LABELS = {
  "strong bullish setup": "강한 상승 흐름",
  "bullish but needs confirmation": "상승 우위이나 확인 필요",
  "neutral / watch": "중립 또는 관찰",
  "weak / reduce risk": "약세, 위험 축소 필요",
  "bearish / sell or avoid": "약세, 매도 또는 회피",
  "data-limited": "데이터 제한",
};

const RISK_PROFILE_LABELS = {
  conservative: "보수적",
  balanced: "균형",
  aggressive: "공격적",
};

export function trendLabel(value) {
  return TREND_LABELS[value] || value || "";
}

export function displayText(value) {
  if (value == null) return "";
  const text = String(value);
  if (TEXT_REPLACEMENTS.has(text)) return TEXT_REPLACEMENTS.get(text);

  const staleMatch = text.match(/^stale market data for: (.+)$/);
  if (staleMatch) return `시장 데이터가 지연된 종목: ${staleMatch[1]}`;

  const technicalCandidateMatch = text.match(
    /^(.+): (BUY|HOLD|REDUCE|SELL|WATCH) candidate from technical score$/,
  );
  if (technicalCandidateMatch) {
    return `${technicalCandidateMatch[1]}: 기술 점수 기준 ${actionLabel(technicalCandidateMatch[2])} 후보`;
  }

  const technicalScoreMatch = text.match(/^technical score (\d+): (.+)$/);
  if (technicalScoreMatch) {
    return `기술 점수 ${technicalScoreMatch[1]}: ${trendLabel(technicalScoreMatch[2])}`;
  }

  const riskWeakMatch = text.match(
    /^(conservative|balanced|aggressive) profile: weak technical setup requires downside control$/,
  );
  if (riskWeakMatch) {
    return `${RISK_PROFILE_LABELS[riskWeakMatch[1]]} 성향: 약한 기술적 흐름이므로 하락 위험 관리가 필요합니다.`;
  }

  const riskSizingMatch = text.match(
    /^(conservative|balanced|aggressive) profile: use position sizing and stop-loss discipline$/,
  );
  if (riskSizingMatch) {
    return `${RISK_PROFILE_LABELS[riskSizingMatch[1]]} 성향: 포지션 크기와 손절 기준을 지키는 것이 중요합니다.`;
  }

  const closeBelowMatch = text.match(/^close below ([0-9.]+)$/);
  if (closeBelowMatch) return `종가가 ${closeBelowMatch[1]} 아래로 내려가면 무효화합니다.`;

  const largestWeightMatch = text.match(/^Largest position weight is ([0-9.]+)%\.$/);
  if (largestWeightMatch) return `최대 보유 비중은 ${largestWeightMatch[1]}%입니다.`;

  return text;
}
