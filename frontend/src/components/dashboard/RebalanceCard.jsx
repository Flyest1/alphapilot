// 목표 배분 대비 드리프트 카드 (Phase 5-2). 자동 실행 없이 검토 제안만 표시한다.
export default function RebalanceCard({ summary }) {
  const drift = summary?.allocation_drift || [];
  const suggestions = summary?.rebalance_suggestions || [];
  if (!drift.length) return null;

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h2>목표 대비 드리프트</h2>
          <p>설정의 목표 배분과 현재 비중 차이입니다. 임계치 초과 시 검토 제안이 표시됩니다.</p>
        </div>
      </div>
      <div className="metric-grid compact">
        {drift.map((row) => (
          <div key={row.key}>
            <span>
              {row.label} (목표 {row.target_pct}%)
            </span>
            <strong className={row.exceeded ? "negative-text" : ""}>
              {row.actual_pct}%{" "}
              <em>
                ({row.drift_pct > 0 ? "+" : ""}
                {row.drift_pct}%p)
              </em>
            </strong>
          </div>
        ))}
      </div>
      {suggestions.length > 0 ? (
        <ul>
          {suggestions.map((text) => (
            <li className="negative-text" key={text}>
              {text}
            </li>
          ))}
        </ul>
      ) : (
        <p className="field-hint">목표 배분 대비 드리프트가 임계치 이내입니다.</p>
      )}
    </section>
  );
}
