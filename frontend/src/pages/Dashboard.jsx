import { useEffect, useState } from "react";

import { api } from "../api/client.js";
import StrategyTable from "../components/StrategyTable.jsx";
import SummaryCard from "../components/SummaryCard.jsx";

function money(value) {
  return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export default function Dashboard() {
  const [summary, setSummary] = useState(null);
  const [latest, setLatest] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.portfolio.summary(), api.reports.latest()])
      .then(([portfolio, reports]) => {
        setSummary(portfolio);
        setLatest(reports);
      })
      .catch((err) => setError(err.message));
  }, []);

  const report = latest?.domestic || latest?.global;
  const content = report?.content || {};

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>Portfolio Dashboard</h1>
          <p>Risk-managed portfolio and report snapshot.</p>
        </div>
      </header>

      {error && <p className="alert">{error}</p>}

      <div className="summary-grid">
        <SummaryCard label="Total value" value={money(summary?.total_market_value)} />
        <SummaryCard
          label="Profit / loss"
          value={money(summary?.total_profit_loss)}
          tone={summary?.total_profit_loss >= 0 ? "positive" : "negative"}
        />
        <SummaryCard
          label="Return rate"
          value={`${summary?.total_return_rate ?? 0}%`}
          tone={summary?.total_return_rate >= 0 ? "positive" : "negative"}
        />
        <SummaryCard label="Cash" value={money(summary?.cash_value)} />
      </div>

      <div className="content-grid">
        <section className="panel">
          <h2>Allocation</h2>
          <div className="bars">
            {(summary?.asset_allocation || []).map((asset) => (
              <div className="bar-row" key={asset.ticker}>
                <div>
                  <strong>{asset.ticker}</strong>
                  <span>{asset.name}</span>
                </div>
                <div className="bar-track">
                  <span style={{ width: `${Math.min(asset.weight, 100)}%` }} />
                </div>
                <em>{asset.weight}%</em>
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <h2>Latest Report</h2>
          <p>{content.market_summary?.summary || summary?.latest_report_summary || "No report yet."}</p>
          <h3>Top opportunities</h3>
          <ul>
            {(content.opportunities || []).slice(0, 4).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
          <h3>Key risks</h3>
          <ul>
            {(content.key_risks || []).slice(0, 4).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      </div>

      <section className="panel">
        <h2>Asset Strategies</h2>
        <StrategyTable strategies={content.asset_strategies || []} />
      </section>
    </section>
  );
}
