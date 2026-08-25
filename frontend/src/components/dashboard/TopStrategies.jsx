import { actionLabel } from "../../api/reports.js";
import {
  compareStrategyBaseConfidence,
  downsideCalibration,
  strategyBaseConfidence,
} from "../../utils/strategyScores.js";

// 보정 전 기술 신호 순 상위 전략/후보 목록. 승률 보정은 순위를 바꾸지 않는다.
export default function TopStrategies({ strategies = [], limit = 5, emptyMessage }) {
  const top = [...strategies].sort(compareStrategyBaseConfidence).slice(0, limit);

  return (
    <div className="top-strategy-list">
      {top.length === 0 && <p className="empty-state">{emptyMessage}</p>}
      {top.map((strategy) => {
        const warning = downsideCalibration(strategy);
        return (
          <div className="top-strategy-row" key={`${strategy.ticker}-${strategy.action}`}>
            <div>
              <strong>{strategy.ticker}</strong>
              <span>{strategy.name}</span>
            </div>
            <span className={`badge ${strategy.action.toLowerCase()}`}>
              {actionLabel(strategy.action)}
            </span>
            <span>
              보정 전 점수 {strategyBaseConfidence(strategy) ?? "-"}/100
              {warning ? ` · 성과 경고 ×${warning.factor}` : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}
