export default function AllocationChart({ allocation = [] }) {
  return (
    <section className="panel">
      <h2>자산 비중</h2>
      <div className="bars">
        {allocation.map((asset) => (
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
  );
}
