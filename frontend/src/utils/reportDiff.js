const CONFIDENCE_CHANGE_THRESHOLD = 10;

function strategyMap(report) {
  const strategies = report?.content?.asset_strategies || [];
  return new Map(strategies.map((strategy) => [strategy.ticker, strategy]));
}

// 직전 리포트 대비 변화: 액션 변경, 큰 신뢰도 변화, 신규/제외 종목 (Phase 6-2)
export function diffReports(current, previous) {
  if (!current || !previous) return null;
  const currentMap = strategyMap(current);
  const previousMap = strategyMap(previous);

  const actionChanges = [];
  const confidenceChanges = [];
  const added = [];
  const removed = [];

  currentMap.forEach((strategy, ticker) => {
    const before = previousMap.get(ticker);
    if (!before) {
      added.push({ ticker, name: strategy.name, action: strategy.action });
      return;
    }
    if (before.action !== strategy.action) {
      actionChanges.push({
        ticker,
        name: strategy.name,
        from: before.action,
        to: strategy.action,
      });
    }
    const delta = Number(strategy.confidence || 0) - Number(before.confidence || 0);
    if (Math.abs(delta) >= CONFIDENCE_CHANGE_THRESHOLD) {
      confidenceChanges.push({
        ticker,
        name: strategy.name,
        from: Number(before.confidence || 0),
        to: Number(strategy.confidence || 0),
        delta,
      });
    }
  });
  previousMap.forEach((strategy, ticker) => {
    if (!currentMap.has(ticker)) {
      removed.push({ ticker, name: strategy.name, action: strategy.action });
    }
  });

  confidenceChanges.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
  const hasChanges =
    actionChanges.length || confidenceChanges.length || added.length || removed.length;
  return {
    previous_created_at: previous.created_at,
    actionChanges,
    confidenceChanges,
    added,
    removed,
    hasChanges: Boolean(hasChanges),
  };
}

// 같은 타입의 직전 리포트를 찾는다. reports는 생성일 내림차순 목록.
export function findPreviousReport(selected, reports = []) {
  if (!selected) return null;
  const sameType = reports.filter((report) => report.report_type === selected.report_type);
  const index = sameType.findIndex((report) => report.id === selected.id);
  if (index === -1 || index + 1 >= sameType.length) return null;
  return sameType[index + 1];
}
