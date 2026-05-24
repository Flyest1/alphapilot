import { useEffect, useState } from "react";

import { api } from "../api/client.js";
import { pickReportWithStrategies, strategyCount } from "../api/reports.js";
import StrategyTable from "../components/StrategyTable.jsx";

export default function Reports() {
  const [latest, setLatest] = useState({});
  const [reports, setReports] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.reports.latest(), api.reports.list()])
      .then(([latestReports, reportList]) => {
        setLatest(latestReports);
        setReports(reportList);
        setSelected(pickReportWithStrategies(latestReports) || reportList[0] || null);
      })
      .catch((err) => setError(err.message));
  }, []);

  const content = selected?.content || {};

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>Reports</h1>
          <p>Domestic and global strategy reports with asset-level risk controls.</p>
        </div>
      </header>
      {error && <p className="alert">{error}</p>}

      <div className="content-grid">
        <section className="panel">
          <h2>Latest</h2>
          <div className="latest-list">
            {["domestic", "global"].map((type) => (
              <button
                key={type}
                type="button"
                onClick={() => latest[type] && setSelected(latest[type])}
                disabled={!latest[type]}
              >
                <strong>{type}</strong>
                <span>
                  {latest[type]?.created_at || "not generated"}
                  {latest[type] ? ` - ${strategyCount(latest[type])} strategies` : ""}
                </span>
              </button>
            ))}
          </div>
        </section>

        <section className="panel">
          <h2>History</h2>
          <div className="report-list">
            {reports.map((report) => (
              <button key={report.id} type="button" onClick={() => setSelected(report)}>
                <strong>{report.title}</strong>
                <span>{report.created_at}</span>
              </button>
            ))}
          </div>
        </section>
      </div>

      <section className="panel">
        <h2>{selected?.title || "No report selected"}</h2>
        <p>{content.market_summary?.summary || "No report content available."}</p>
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
        <StrategyTable strategies={content.asset_strategies || []} />
      </section>
    </section>
  );
}
