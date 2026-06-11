import { actionLabel } from "../../api/reports.js";

// 신뢰도 순 상위 전략/후보 목록. 대시보드의 "최신 전략 요약"과 "추가 매수 후보"가 함께 쓴다.
export default function TopStrategies({ strategies = [], limit = 5, emptyMessage }) {
  const top = [...strategies]
    .sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
    .slice(0, limit);

  return (
    <div className="top-strategy-list">
      {top.length === 0 && <p className="empty-state">{emptyMessage}</p>}
      {top.map((strategy) => (
        <div className="top-strategy-row" key={`${strategy.ticker}-${strategy.action}`}>
          <div>
            <strong>{strategy.ticker}</strong>
            <span>{strategy.name}</span>
          </div>
          <span className={`badge ${strategy.action.toLowerCase()}`}>
            {actionLabel(strategy.action)}
          </span>
          <span>{strategy.confidence}%</span>
        </div>
      ))}
    </div>
  );
}
