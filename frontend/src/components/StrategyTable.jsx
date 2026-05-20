function formatRange(low, high) {
  if (low == null && high == null) return "-";
  return `${low ?? "-"} - ${high ?? "-"}`;
}

export default function StrategyTable({ strategies = [] }) {
  if (!strategies.length) {
    return <p className="empty-state">No strategy rows available.</p>;
  }

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Ticker</th>
            <th>Action</th>
            <th>Confidence</th>
            <th>Buy range</th>
            <th>Target</th>
            <th>Stop loss</th>
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
              <td>{strategy.confidence}%</td>
              <td>{formatRange(strategy.buy_range_low, strategy.buy_range_high)}</td>
              <td>{strategy.target_price ?? "-"}</td>
              <td>{strategy.stop_loss ?? "-"}</td>
              <td>{strategy.risk}</td>
              <td>{strategy.invalidation_condition}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
