import {
  displayText,
  formatStrategyMessageValue,
  importantStrategyMessages,
} from "../api/reports.js";

function formatRange(strategy) {
  const low = formatStrategyMessageValue(strategy.buy_range_low);
  const current = formatStrategyMessageValue(strategy.current_price);
  const high = formatStrategyMessageValue(strategy.buy_range_high);
  const parts = [low, current, high].filter(Boolean);
  return parts.length ? parts.join("~") : "-";
}

function formatValue(value) {
  return formatStrategyMessageValue(value) || "-";
}

export default function KeyMessageList({ strategies = [], limit = 8 }) {
  const messages = importantStrategyMessages(strategies, limit);

  if (!messages.length) {
    return <p className="empty-state">핵심 매매 메시지를 만들 수 있는 전략이 아직 없습니다.</p>;
  }

  return (
    <div className="key-message-list">
      {messages.map((message) => {
        const strategy = message.strategy || {};
        return (
          <details className="key-message-item" key={message.key}>
            <summary>
              <strong>{message.text}</strong>
              {message.rangeLine && <span>{message.rangeLine}</span>}
              {message.exitLine && <span>{message.exitLine}</span>}
            </summary>
            <dl className="key-message-detail-grid">
              <div>
                <dt>현재가</dt>
                <dd>{formatValue(strategy.current_price)}</dd>
              </div>
              <div>
                <dt>신뢰도</dt>
                <dd>{strategy.confidence == null ? "-" : `${strategy.confidence}%`}</dd>
              </div>
              <div>
                <dt>매수구간</dt>
                <dd>{formatRange(strategy)}</dd>
              </div>
              <div>
                <dt>목표</dt>
                <dd>{formatValue(strategy.target_price)}</dd>
              </div>
              <div>
                <dt>손절</dt>
                <dd>{formatValue(strategy.stop_loss)}</dd>
              </div>
            </dl>
            <div className="key-message-detail-notes">
              {strategy.reasoning && (
                <p>
                  <strong>판단 근거</strong>
                  <span>{displayText(strategy.reasoning)}</span>
                </p>
              )}
              {strategy.risk && (
                <p>
                  <strong>위험 요인</strong>
                  <span>{displayText(strategy.risk)}</span>
                </p>
              )}
              {strategy.invalidation_condition && (
                <p>
                  <strong>무효화 조건</strong>
                  <span>{displayText(strategy.invalidation_condition)}</span>
                </p>
              )}
            </div>
          </details>
        );
      })}
    </div>
  );
}
