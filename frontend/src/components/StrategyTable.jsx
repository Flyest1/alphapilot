import { actionLabel, displayText } from "../api/reports.js";

function formatRange(low, high) {
  if (low == null && high == null) return "-";
  return `${low ?? "-"} - ${high ?? "-"}`;
}

function isDataLimited(strategy) {
  return strategy.reasoning === "data-limited";
}

export default function StrategyTable({ strategies = [] }) {
  if (!strategies.length) {
    return <p className="empty-state">표시할 전략이 없습니다.</p>;
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
                <span className={`badge ${strategy.action.toLowerCase()}`}>
                  {actionLabel(strategy.action)}
                </span>
                {isDataLimited(strategy) && <span className="status-pill warning">데이터 제한</span>}
              </div>
            </div>
            <dl>
              <div>
                <dt>현재가</dt>
                <dd>{strategy.current_price ?? "-"}</dd>
              </div>
              <div>
                <dt>신뢰도</dt>
                <dd>{strategy.confidence}%</dd>
              </div>
              <div>
                <dt>매수 구간</dt>
                <dd>{formatRange(strategy.buy_range_low, strategy.buy_range_high)}</dd>
              </div>
              <div>
                <dt>목표가</dt>
                <dd>{strategy.target_price ?? "-"}</dd>
              </div>
              <div>
                <dt>손절가</dt>
                <dd>{strategy.stop_loss ?? "-"}</dd>
              </div>
              <div className="wide-definition">
                <dt>위험 요인</dt>
                <dd>{displayText(strategy.risk)}</dd>
              </div>
              <div className="wide-definition">
                <dt>판단 근거</dt>
                <dd>{displayText(strategy.reasoning)}</dd>
              </div>
              <div className="wide-definition">
                <dt>무효화 조건</dt>
                <dd>{displayText(strategy.invalidation_condition)}</dd>
              </div>
            </dl>
          </article>
        ))}
      </div>
      <div className="table-wrap strategy-table">
        <table>
          <thead>
            <tr>
              <th>티커</th>
              <th>전략</th>
              <th>상태</th>
              <th>현재가</th>
              <th>신뢰도</th>
              <th>매수 구간</th>
              <th>목표가</th>
              <th>손절가</th>
              <th>판단 근거</th>
              <th>위험 요인</th>
              <th>무효화 조건</th>
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
                  <span className={`badge ${strategy.action.toLowerCase()}`}>
                    {actionLabel(strategy.action)}
                  </span>
                </td>
                <td>
                  {isDataLimited(strategy) ? (
                    <span className="status-pill warning">데이터 제한</span>
                  ) : (
                    <span className="status-pill">정상</span>
                  )}
                </td>
                <td>{strategy.current_price ?? "-"}</td>
                <td>{strategy.confidence}%</td>
                <td>{formatRange(strategy.buy_range_low, strategy.buy_range_high)}</td>
                <td>{strategy.target_price ?? "-"}</td>
                <td>{strategy.stop_loss ?? "-"}</td>
                <td>{displayText(strategy.reasoning)}</td>
                <td>{displayText(strategy.risk)}</td>
                <td>{displayText(strategy.invalidation_condition)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
