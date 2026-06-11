import { formatMoney } from "../../utils/formatters.js";

function PortfolioCharts({ points = [] }) {
  if (points.length < 2) {
    return <p className="empty-state">차트로 표시할 기간 데이터가 아직 부족합니다.</p>;
  }
  const maxAbsChange = Math.max(
    ...points.map((point) => Math.abs(Number(point.daily_profit_loss || 0))),
    1,
  );
  const values = points.map((point) => Number(point.total_market_value || 0));
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);
  const valueRange = Math.max(maxValue - minValue, 1);

  return (
    <div className="portfolio-chart-grid">
      <div>
        <h3>일간 변동 금액</h3>
        <div className="change-chart">
          {points.map((point) => {
            const change = Number(point.daily_profit_loss || 0);
            return (
              <span
                className={change >= 0 ? "positive" : "negative"}
                key={`change-${point.date}`}
                style={{ height: `${Math.max(4, (Math.abs(change) / maxAbsChange) * 100)}%` }}
                title={`${point.date}: ${change.toLocaleString()} KRW`}
              />
            );
          })}
        </div>
      </div>
      <div>
        <h3>총 평가금액</h3>
        <div className="value-chart">
          {points.map((point) => {
            const value = Number(point.total_market_value || 0);
            return (
              <span
                key={`value-${point.date}`}
                style={{ height: `${Math.max(8, ((value - minValue) / valueRange) * 92 + 8)}%` }}
                title={`${point.date}: ${value.toLocaleString()} KRW`}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default function TrendChart({ summary, chartRange, onChangeRange }) {
  const dailyChanges = (summary?.daily_asset_changes || []).slice(0, 8);
  const chartPoints = (summary?.value_history || []).slice(chartRange === "7d" ? -7 : -30);

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h2>일별 자산 변동</h2>
          <p>최신 거래일 종가와 직전 거래일 종가 차이를 KRW 기준으로 환산한 값입니다.</p>
        </div>
        <div className="inline-metrics">
          <span>{summary?.daily_return_rate ?? 0}%</span>
          <span>현금 {formatMoney(summary?.cash_value)} KRW</span>
        </div>
      </div>
      <div className="filter-row">
        <button
          className={chartRange === "7d" ? "active" : ""}
          type="button"
          onClick={() => onChangeRange("7d")}
        >
          7일
        </button>
        <button
          className={chartRange === "30d" ? "active" : ""}
          type="button"
          onClick={() => onChangeRange("30d")}
        >
          1달
        </button>
      </div>
      <PortfolioCharts points={chartPoints} />
      <div className="daily-change-list">
        {dailyChanges.length === 0 && (
          <p className="empty-state">표시할 일별 변동 데이터가 아직 없습니다.</p>
        )}
        {dailyChanges.map((asset) => (
          <div className="daily-change-row" key={`${asset.market}-${asset.ticker}`}>
            <div>
              <strong>{asset.ticker}</strong>
              <span>{asset.name}</span>
            </div>
            <div className="daily-change-track">
              <span
                className={asset.daily_profit_loss >= 0 ? "positive" : "negative"}
                style={{
                  width: `${Math.min(
                    100,
                    Math.max(6, Math.abs(asset.daily_return_rate || 0) * 12),
                  )}%`,
                }}
              />
            </div>
            <em className={asset.daily_profit_loss >= 0 ? "positive-text" : "negative-text"}>
              {formatMoney(asset.daily_profit_loss)} KRW · {asset.daily_return_rate}%
            </em>
          </div>
        ))}
      </div>
    </section>
  );
}
