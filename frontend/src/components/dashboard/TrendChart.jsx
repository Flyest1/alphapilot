import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatMoney } from "../../utils/formatters.js";

function compactKrw(value) {
  const numeric = Number(value || 0);
  if (Math.abs(numeric) >= 100000000) return `${(numeric / 100000000).toFixed(1)}억`;
  if (Math.abs(numeric) >= 10000) return `${Math.round(numeric / 10000).toLocaleString()}만`;
  return numeric.toLocaleString();
}

function PortfolioTrend({ points = [] }) {
  if (points.length < 2) {
    return <p className="empty-state">차트로 표시할 기간 데이터가 아직 부족합니다.</p>;
  }
  const data = points.map((point) => ({
    date: point.date,
    total: Number(point.total_market_value || 0),
    change: Number(point.daily_profit_loss || 0),
  }));

  return (
    <div className="benchmark-recharts">
      <ResponsiveContainer height="100%" width="100%">
        <ComposedChart data={data} margin={{ top: 12, right: 8, bottom: 4, left: 8 }}>
          <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
          <XAxis
            dataKey="date"
            minTickGap={28}
            stroke="#64748b"
            tick={{ fontSize: 12 }}
            tickFormatter={(value) => String(value).slice(5)}
          />
          <YAxis
            domain={["auto", "auto"]}
            stroke="#64748b"
            tick={{ fontSize: 12 }}
            tickFormatter={compactKrw}
            width={56}
            yAxisId="total"
          />
          <YAxis hide yAxisId="change" />
          <Tooltip
            formatter={(value, name) => [
              `${formatMoney(value)} KRW`,
              name === "total" ? "총 평가금액" : "일간 변동",
            ]}
            labelFormatter={(label) => `날짜: ${label}`}
          />
          <Bar dataKey="change" name="change" opacity={0.7} yAxisId="change">
            {data.map((entry) => (
              <Cell fill={entry.change >= 0 ? "#0f766e" : "#be123c"} key={`bar-${entry.date}`} />
            ))}
          </Bar>
          <Line
            dataKey="total"
            dot={false}
            name="total"
            stroke="#2563eb"
            strokeWidth={2.5}
            type="monotone"
            yAxisId="total"
          />
        </ComposedChart>
      </ResponsiveContainer>
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
      <PortfolioTrend points={chartPoints} />
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
