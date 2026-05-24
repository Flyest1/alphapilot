export function strategyCount(report) {
  return report?.content?.asset_strategies?.length || 0;
}

export function pickReportWithStrategies(latestReports = {}) {
  const reports = [latestReports.domestic, latestReports.global].filter(Boolean);
  return reports.find((report) => strategyCount(report) > 0) || reports[0] || null;
}
