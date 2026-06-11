import { actionLabel, displayText } from "../api/reports.js";
import { formatReturn, formatValue } from "../utils/formatters.js";

function formatRange(low, high) {
  if (low == null && high == null) return "-";
  return `${low ?? "-"} - ${high ?? "-"}`;
}

function isDataLimited(strategy) {
  return strategy.reasoning === "data-limited";
}

function performanceFor(strategy, performanceLogs) {
  return performanceLogs.find(
    (row) => row.ticker === strategy.ticker && row.action === strategy.action,
  );
}

export default function StrategyTable({ strategies = [], performanceLogs = [] }) {
  if (!strategies.length) {
    return <p className="empty-state">표시할 전략이 없습니다.</p>;
  }

  return (
    <div className="strategy-accordion">
      {strategies.map((strategy) => {
        const performance = performanceFor(strategy, performanceLogs);
        return (
          <details
            className={`strategy-detail ${isDataLimited(strategy) ? "data-limited" : ""}`}
            key={`${strategy.ticker}-${strategy.action}-${strategy.reasoning}`}
          >
            <summary>
              <span>
                <strong>{strategy.ticker}</strong>
                <em>{strategy.name}</em>
              </span>
              <span className={`badge ${strategy.action.toLowerCase()}`}>
                {actionLabel(strategy.action)}
              </span>
              {isDataLimited(strategy) && <span className="status-pill warning">데이터 제한</span>}
            </summary>
            <dl>
              <div>
                <dt>현재가</dt>
                <dd>{formatValue(strategy.current_price)}</dd>
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
                <dd>{formatValue(strategy.target_price)}</dd>
              </div>
              <div>
                <dt>손절가</dt>
                <dd>{formatValue(strategy.stop_loss)}</dd>
              </div>
              <div>
                <dt>1일 변동</dt>
                <dd>{formatReturn(performance?.return_after_1d)}</dd>
              </div>
              <div>
                <dt>5일 변동</dt>
                <dd>{formatReturn(performance?.return_after_5d)}</dd>
              </div>
              <div>
                <dt>20일 변동</dt>
                <dd>{formatReturn(performance?.return_after_20d)}</dd>
              </div>
              {isDataLimited(strategy) && (
                <div className="wide-definition">
                  <dt>상태</dt>
                  <dd>{displayText(strategy.reasoning)}</dd>
                </div>
              )}
            </dl>
          </details>
        );
      })}
    </div>
  );
}
