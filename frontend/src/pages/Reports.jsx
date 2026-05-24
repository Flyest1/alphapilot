import { useEffect, useState } from "react";

import { api } from "../api/client.js";
import {
  dataLimitedCount,
  formatReportTime,
  isTechnicalOnlyReport,
  pickReportWithStrategies,
  reportTypeLabel,
  strategyCount,
} from "../api/reports.js";
import StrategyTable from "../components/StrategyTable.jsx";

const reportTypes = ["domestic", "global"];

function firstReportForType(latest, reports, type) {
  return latest[type] || reports.find((report) => report.report_type === type) || null;
}

export default function Reports() {
  const [latest, setLatest] = useState({});
  const [reports, setReports] = useState([]);
  const [selected, setSelected] = useState(null);
  const [activeType, setActiveType] = useState("domestic");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.reports.latest(), api.reports.list()])
      .then(([latestReports, reportList]) => {
        const initialReport = pickReportWithStrategies(latestReports) || reportList[0] || null;
        setLatest(latestReports);
        setReports(reportList);
        setSelected(initialReport);
        setActiveType(initialReport?.report_type || "domestic");
      })
      .catch((err) => setError(err.message))
      .finally(() => setIsLoading(false));
  }, []);

  const content = selected?.content || {};
  const filteredReports = reports.filter((report) => report.report_type === activeType);
  const latestForActiveType = latest[activeType];
  const selectedStrategyCount = strategyCount(selected);
  const selectedDataLimitedCount = dataLimitedCount(selected);
  const selectedTechnicalOnly = isTechnicalOnlyReport(selected);

  function selectType(type) {
    setActiveType(type);
    setSelected(firstReportForType(latest, reports, type));
  }

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>Reports</h1>
          <p>Domestic and global strategy reports with asset-level risk controls.</p>
        </div>
      </header>
      {error && <p className="alert">{error}</p>}
      {isLoading && <p className="empty-state">Loading reports.</p>}

      <div className="segmented-control">
        {reportTypes.map((type) => (
          <button
            className={activeType === type ? "active" : ""}
            key={type}
            type="button"
            onClick={() => selectType(type)}
          >
            <strong>{reportTypeLabel(type)}</strong>
            <span>{strategyCount(latest[type])} strategies</span>
          </button>
        ))}
      </div>

      <div className="content-grid">
        <section className="panel">
          <h2>Latest {reportTypeLabel(activeType)}</h2>
          <div className="metric-grid compact">
            <div>
              <span>Generated</span>
              <strong>{formatReportTime(latestForActiveType?.created_at)}</strong>
            </div>
            <div>
              <span>Strategies</span>
              <strong>{strategyCount(latestForActiveType)}</strong>
            </div>
            <div>
              <span>Data-limited</span>
              <strong>{dataLimitedCount(latestForActiveType)}</strong>
            </div>
            <div>
              <span>AI mode</span>
              <strong>{isTechnicalOnlyReport(latestForActiveType) ? "Fallback" : "AI"}</strong>
            </div>
          </div>
        </section>

        <section className="panel">
          <h2>{reportTypeLabel(activeType)} History</h2>
          <div className="report-list">
            {!isLoading && filteredReports.length === 0 && (
              <p className="empty-state">No reports generated yet.</p>
            )}
            {filteredReports.map((report) => (
              <button
                className={selected?.id === report.id ? "active" : ""}
                key={report.id}
                type="button"
                onClick={() => setSelected(report)}
              >
                <strong>{report.title}</strong>
                <span>
                  {formatReportTime(report.created_at)} - {strategyCount(report)} strategies
                </span>
              </button>
            ))}
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>{selected?.title || "No report selected"}</h2>
            <p>{formatReportTime(selected?.created_at)}</p>
          </div>
          <div className="inline-metrics">
            <span>{selectedStrategyCount} strategies</span>
            <span>{selectedDataLimitedCount} data-limited</span>
            {selectedTechnicalOnly && <span>technical-only</span>}
          </div>
        </div>
        <p>{content.market_summary?.summary || "No report content available."}</p>
        {!!content.market_summary?.key_indices?.length && (
          <div className="index-list">
            {content.market_summary.key_indices.map((index) => (
              <span key={index.name || JSON.stringify(index)}>
                {index.name}: {index.technical_score ?? "-"} {index.trend_label || ""}
              </span>
            ))}
          </div>
        )}
        <div className="risk-grid">
          <div>
            <h3>Opportunities</h3>
            <ul>
              {(content.opportunities || []).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3>Key risks</h3>
            <ul>
              {(content.key_risks || []).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>Asset-Level Strategy</h2>
        {isLoading ? (
          <p className="empty-state">Loading strategies.</p>
        ) : (
          <StrategyTable strategies={content.asset_strategies || []} />
        )}
      </section>
    </section>
  );
}
