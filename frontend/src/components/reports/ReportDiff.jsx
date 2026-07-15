import { actionLabel, formatReportTime } from "../../api/reports.js";
import { diffReports } from "../../utils/reportDiff.js";

// 직전 리포트 대비 변화 요약 (Phase 6-2)
export default function ReportDiff({ selected, previous }) {
  const diff = diffReports(selected, previous);
  if (!diff) return null;

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h2>직전 리포트 대비 변화</h2>
          <p>{formatReportTime(diff.previous_created_at)} 리포트와 비교한 결과입니다.</p>
        </div>
      </div>
      {!diff.hasChanges && (
        <p className="empty-state">직전 리포트와 비교해 액션/신뢰도/종목 구성 변화가 없습니다.</p>
      )}
      {diff.actionChanges.length > 0 && (
        <>
          <h3>액션 변경</h3>
          <ul>
            {diff.actionChanges.map((row) => (
              <li key={`action-${row.ticker}`}>
                <strong>{row.ticker}</strong> {row.name}:{" "}
                <span className={`badge ${row.from.toLowerCase()}`}>{actionLabel(row.from)}</span>
                {" → "}
                <span className={`badge ${row.to.toLowerCase()}`}>{actionLabel(row.to)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {diff.confidenceChanges.length > 0 && (
        <>
          <h3>신호 점수 변화 (±10 이상)</h3>
          <ul>
            {diff.confidenceChanges.map((row) => (
              <li key={`confidence-${row.ticker}`}>
                <strong>{row.ticker}</strong> {row.name}: {row.from}/100 → {row.to}/100{" "}
                <em className={row.delta >= 0 ? "positive-text" : "negative-text"}>
                  ({row.delta > 0 ? "+" : ""}
                  {row.delta})
                </em>
              </li>
            ))}
          </ul>
        </>
      )}
      {diff.added.length > 0 && (
        <>
          <h3>신규 종목</h3>
          <ul>
            {diff.added.map((row) => (
              <li className="positive-text" key={`added-${row.ticker}`}>
                <strong>{row.ticker}</strong> {row.name} ({actionLabel(row.action)})
              </li>
            ))}
          </ul>
        </>
      )}
      {diff.removed.length > 0 && (
        <>
          <h3>제외 종목</h3>
          <ul>
            {diff.removed.map((row) => (
              <li key={`removed-${row.ticker}`}>
                <strong>{row.ticker}</strong> {row.name} (직전: {actionLabel(row.action)})
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
