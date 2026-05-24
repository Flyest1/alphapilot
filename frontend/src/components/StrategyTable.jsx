function formatRange(low, high) {
  if (low == null && high == null) return "-";
  return `${low ?? "-"} - ${high ?? "-"}`;
}

function isDataLimited(strategy) {
  return strategy.reasoning === "data-limited";
}

export default function StrategyTable({ strategies = [] }) {
  if (!strategies.length) {
    return <p className="empty-state">No strategy rows available.</p>;
  }

  return (
    <>
      <div className="strategy-card-list">
        {strategies.map((strategy) => (
          <article
            className={`strategy-card ${isDataLimited(strategy) ? "data-limited" : ""}`}
            key={`${strategy.ticker}-${strategy.action}-${strategy.reasoning}`}
          >
            <div className="strategy-card-header">
              <div>
                <strong>{strategy.ticker}</strong>
                <span>{strategy.name}</span>
              </div>
              <div className="badge-stack">
                <span className={`badge ${strategy.action.toLowerCase()}`}>{strategy.action}</span>
                {isDataLimited(strategy) && <span className="status-pill warning">data-limited</span>}
              </div>
            </div>
            <dl>
              <div>
                <dt>Current price</dt>
                <dd>{strategy.current_price ?? "-"}</dd>
              </div>
              <div>
                <dt>Confidence</dt>
                <dd>{strategy.confidence}%</dd>
              </div>
              <div>
                <dt>Buy range</dt>
                <dd>{formatRange(strategy.buy_range_low, strategy.buy_range_high)}</dd>
              </div>
              <div>
                <dt>Target</dt>
                <dd>{strategy.target_price ?? "-"}</dd>
              </div>
              <div>
                <dt>Stop loss</dt>
                <dd>{strategy.stop_loss ?? "-"}</dd>
              </div>
              <div className="wide-definition">
                <dt>Risk</dt>
                <dd>{strategy.risk}</dd>
              </div>
              <div className="wide-definition">
                <dt>Reasoning</dt>
                <dd>{strategy.reasoning}</dd>
              </div>
              <div className="wide-definition">
                <dt>Invalidation</dt>
                <dd>{strategy.invalidation_condition}</dd>
              </div>
            </dl>
          </article>
        ))}
      </div>
      <div className="table-wrap strategy-table">
        <table>
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Action</th>
              <th>Status</th>
              <th>Current</th>
              <th>Confidence</th>
              <th>Buy range</th>
              <th>Target</th>
              <th>Stop loss</th>
              <th>Reasoning</th>
              <th>Risk</th>
              <th>Invalidation</th>
            </tr>
          </thead>
          <tbody>
            {strategies.map((strategy) => (
              <tr key={`${strategy.ticker}-${strategy.action}-${strategy.reasoning}`}>
                <td>
                  <strong>{strategy.ticker}</strong>
                  <span>{strategy.name}</span>
                </td>
                <td>
                  <span className={`badge ${strategy.action.toLowerCase()}`}>{strategy.action}</span>
                </td>
                <td>
                  {isDataLimited(strategy) ? (
                    <span className="status-pill warning">data-limited</span>
                  ) : (
                    <span className="status-pill">ok</span>
                  )}
                </td>
                <td>{strategy.current_price ?? "-"}</td>
                <td>{strategy.confidence}%</td>
                <td>{formatRange(strategy.buy_range_low, strategy.buy_range_high)}</td>
                <td>{strategy.target_price ?? "-"}</td>
                <td>{strategy.stop_loss ?? "-"}</td>
                <td>{strategy.reasoning}</td>
                <td>{strategy.risk}</td>
                <td>{strategy.invalidation_condition}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
