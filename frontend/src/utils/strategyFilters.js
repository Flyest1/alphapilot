import { compareStrategyBaseConfidence } from "./strategyScores.js";

export const STRATEGY_FILTERS = ["ALL", "BUY", "HOLD", "REDUCE", "SELL", "WATCH", "DATA_LIMITED"];

export const STRATEGY_SORTS = [
  { key: "default", label: "기본 순서" },
  { key: "confidence", label: "보정 전 점수순" },
  { key: "return20d", label: "20일 수익률순" },
];

export function filterStrategies(strategies = [], filter = "ALL") {
  return strategies.filter((strategy) => {
    if (filter === "ALL") return true;
    if (filter === "DATA_LIMITED") return strategy.reasoning === "data-limited";
    return strategy.action === filter;
  });
}

function return20dFor(strategy, performanceLogs) {
  const log = performanceLogs.find(
    (row) => row.ticker === strategy.ticker && row.action === strategy.action,
  );
  const numeric = Number(log?.return_after_20d);
  return Number.isFinite(numeric) ? numeric : null;
}

// 정렬: 보정 전 기술 신호순 또는 20일 수익률순(성과 로그 기준, 값 없는 항목은 뒤로).
export function sortStrategies(strategies = [], sortKey = "default", performanceLogs = []) {
  if (sortKey === "confidence") {
    return [...strategies].sort(compareStrategyBaseConfidence);
  }
  if (sortKey === "return20d") {
    return [...strategies].sort((a, b) => {
      const aReturn = return20dFor(a, performanceLogs);
      const bReturn = return20dFor(b, performanceLogs);
      if (aReturn == null && bReturn == null) return 0;
      if (aReturn == null) return 1;
      if (bReturn == null) return -1;
      return bReturn - aReturn;
    });
  }
  return strategies;
}
