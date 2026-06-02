import { formatStrategyMessageValue, importantStrategyMessages } from "../api/reports.js";

function formatRange(strategy) {
  const low = formatStrategyMessageValue(strategy.buy_range_low);
  const high = formatStrategyMessageValue(strategy.buy_range_high);
  if (low && high) return `${low} - ${high}`;
  return low || high || "-";
}

function formatValue(value) {
  return formatStrategyMessageValue(value) || "-";
}

function numericValue(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function formatCurrentPercent(value, currentPrice) {
  const numeric = numericValue(value);
  const current = numericValue(currentPrice);
  if (numeric == null || current == null || current === 0) return "";

  const percent = ((numeric - current) / current) * 100;
  const formatted = percent.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return `(${formatted}%)`;
}

function performanceFor(strategy, performanceLogs) {
  return performanceLogs.find(
    (row) => row.ticker === strategy.ticker && row.action === strategy.action,
  );
}

function formatReturn(value) {
  const numeric = numericValue(value);
  if (numeric == null) return "-";
  return `${numeric.toFixed(2)}%`;
}

function RangeLine({ strategy }) {
  const low = formatStrategyMessageValue(strategy.buy_range_low);
  const current = formatStrategyMessageValue(strategy.current_price);
  const high = formatStrategyMessageValue(strategy.buy_range_high);

  if (!low && !current && !high) return null;

  return (
    <span className="key-message-range-line">
      매수구간{" "}
      {low && (
        <>
          {low}
          {formatCurrentPercent(strategy.buy_range_low, strategy.current_price)}
        </>
      )}
      {low && current && "~"}
      {current && <b className="key-message-range-current">{current}</b>}
      {current && high && "~"}
      {high && (
        <>
          {high}
          {formatCurrentPercent(strategy.buy_range_high, strategy.current_price)}
        </>
      )}
    </span>
  );
}

function ExitLine({ strategy }) {
  const target = formatStrategyMessageValue(strategy.target_price);
  const stop = formatStrategyMessageValue(strategy.stop_loss);
  const confidence =
    strategy.confidence == null || strategy.confidence === "" ? "" : `신뢰도 ${strategy.confidence}%`;
  const parts = [
    target ? `목표 ${target}${formatCurrentPercent(strategy.target_price, strategy.current_price)}` : "",
    stop ? `손절 ${stop}${formatCurrentPercent(strategy.stop_loss, strategy.current_price)}` : "",
    confidence,
  ].filter(Boolean);

  return parts.length ? <span>{parts.join(", ")}</span> : null;
}

export default function KeyMessageList({ strategies = [], limit = 8, performanceLogs = [] }) {
  const messages = importantStrategyMessages(strategies, limit);

  if (!messages.length) {
    return <p className="empty-state">핵심 매매 메시지를 만들 수 있는 전략이 아직 없습니다.</p>;
  }

  return (
    <div className="key-message-list">
      {messages.map((message) => {
        const strategy = message.strategy || {};
        const performance = performanceFor(strategy, performanceLogs);
        return (
          <details className="key-message-item" key={message.key}>
            <summary>
              <strong>{message.text}</strong>
              <RangeLine strategy={strategy} />
              <ExitLine strategy={strategy} />
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
            </dl>
          </details>
        );
      })}
    </div>
  );
}
