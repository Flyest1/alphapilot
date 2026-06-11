export const STRATEGY_FILTERS = ["ALL", "BUY", "HOLD", "REDUCE", "SELL", "WATCH", "DATA_LIMITED"];

export function filterStrategies(strategies = [], filter = "ALL") {
  return strategies.filter((strategy) => {
    if (filter === "ALL") return true;
    if (filter === "DATA_LIMITED") return strategy.reasoning === "data-limited";
    return strategy.action === filter;
  });
}
