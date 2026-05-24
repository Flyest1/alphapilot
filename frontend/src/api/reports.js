export function strategyCount(report) {
  return report?.content?.asset_strategies?.length || 0;
}

export function dataLimitedCount(report) {
  return (
    report?.content?.asset_strategies?.filter((strategy) => strategy.reasoning === "data-limited")
      .length || 0
  );
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
  return reportType === "domestic" ? "Domestic" : "Global";
}

export function formatReportTime(value) {
  if (!value) return "not generated";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
