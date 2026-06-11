import { actionLabel, displayText } from "../api/reports.js";
import { formatReturn, formatValue } from "../utils/formatters.js";
import { confidenceBadge } from "../utils/recommendationStats.js";

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

function confidenceDetailText(detail) {
  const parts = [`기술 점수 기여 ${detail.technical_confidence}`];
  if (detail.win_rate != null) {
    parts.push(
      `과거 승률 ${Math.round(detail.win_rate * 100)}% (종료 표본 ${detail.sample_size}건` +
        `${detail.calibrated ? `, 보정계수 ×${detail.calibration_factor}` : ", 보정 미적용"})`,
    );
  } else {
    parts.push("과거 승률 표본 없음");
  }
  parts.push(detail.news_context_used ? "뉴스 컨텍스트 반영" : "뉴스 컨텍스트 미반영");
  return parts.join(" · ");
}

function dataQualityText(inputs) {
  const parts = [`제공자 ${inputs.provider || "-"}`];
  if (inputs.last_trading_date) {
    parts.push(`최근 거래일 ${String(inputs.last_trading_date).slice(0, 10)}`);
  }
  parts.push(inputs.is_stale ? "데이터 지연" : "데이터 최신");
  return parts.join(" · ");
}

export default function StrategyTable({ strategies = [], performanceLogs = [], inputsByTicker }) {
  if (!strategies.length) {
    return <p className="empty-state">표시할 전략이 없습니다.</p>;
  }

  return (
    <div className="strategy-accordion">
      {strategies.map((strategy) => {
        const performance = performanceFor(strategy, performanceLogs);
        const badge = confidenceBadge(strategy.confidence_detail);
        const inputs = inputsByTicker?.[strategy.ticker];
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
              {!isDataLimited(strategy) && badge && (
                <span className={`status-pill ${badge.kind === "calibrated" ? "ok" : "warning"}`}>
                  {badge.label}
                </span>
              )}
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
              {strategy.confidence_detail && !isDataLimited(strategy) && (
                <div className="wide-definition">
                  <dt>신뢰도 근거</dt>
                  <dd>{confidenceDetailText(strategy.confidence_detail)}</dd>
                </div>
              )}
              {inputs && (
                <div className="wide-definition">
                  <dt>데이터 품질</dt>
                  <dd>{dataQualityText(inputs)}</dd>
                </div>
              )}
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
