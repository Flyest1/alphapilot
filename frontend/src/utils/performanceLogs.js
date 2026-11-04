// Performance logs are created per strategy row of a report. Matching by ticker alone would show
// another report's outcome, so logs are scoped to the displayed report whenever both sides carry
// a report id. Legacy rows without report_id remain visible as a fallback.
export function logsForReport(performanceLogs = [], reportId) {
  if (!reportId) return performanceLogs;
  return performanceLogs.filter((row) => row.report_id == null || row.report_id === reportId);
}

// Logs arrive newest first, so the first ticker/action match is the most recent outcome.
export function findPerformanceLog(strategy, performanceLogs = []) {
  return performanceLogs.find(
    (row) => row.ticker === strategy.ticker && row.action === strategy.action,
  );
}
