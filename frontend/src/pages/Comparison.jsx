import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api, isApiCacheFresh, readApiCache } from "../api/client.js";
import Skeleton from "../components/Skeleton.jsx";
import { MESSAGES } from "../constants/strings.js";
import { formatPercent } from "../utils/formatters.js";

const colorByKey = {
  kospi: "#0f766e",
  kosdaq: "#2563eb",
  sp500: "#7c3aed",
  nasdaq: "#ea580c",
  alphapilot: "#be123c",
  actual_portfolio: "#111827",
};

const rangeOptions = [
  { label: "5일", value: 5 },
  { label: "10일", value: 10 },
  { label: "30일", value: 30 },
  { label: "60일", value: 60 },
  { label: "120일", value: 120 },
];

const COMPARISON_CACHE_MS = 5 * 60 * 1000;

function validReturnPoints(points = []) {
  const pointsByDate = new Map();
  points.forEach((point) => {
    const returnRate = Number(point?.return_rate);
    if (point?.date && Number.isFinite(returnRate)) {
      pointsByDate.set(point.date, returnRate);
    }
  });
  return pointsByDate;
}

function rebasedReturnRate(returnRate, baselineReturnRate) {
  return ((1 + returnRate / 100) / (1 + baselineReturnRate / 100) - 1) * 100;
}

export function alignComparisonSeries(series = []) {
  const usableSeries = series
    .map((row) => ({ ...row, pointsByDate: validReturnPoints(row.points) }))
    .filter((row) => row.pointsByDate.size > 0);
  if (!usableSeries.length) return { chartData: [], commonStartDate: null, series: [] };

  const commonDates = [...usableSeries[0].pointsByDate.keys()].filter((date) =>
    usableSeries.every((row) => row.pointsByDate.has(date)),
  );
  const commonStartDate = commonDates.sort((left, right) => left.localeCompare(right))[0];
  if (!commonStartDate) return { chartData: [], commonStartDate: null, series: usableSeries };

  const alignedSeries = usableSeries.map(({ pointsByDate, ...row }) => {
    const baselineReturnRate = pointsByDate.get(commonStartDate);
    const points = [...pointsByDate.entries()]
      .filter(([date]) => date >= commonStartDate)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([date, returnRate]) => ({
        date,
        return_rate: rebasedReturnRate(returnRate, baselineReturnRate),
      }));
    return { ...row, points };
  });
  const chartByDate = new Map();
  alignedSeries.forEach((row) => {
    row.points.forEach((point) => {
      if (!chartByDate.has(point.date)) chartByDate.set(point.date, { date: point.date });
      chartByDate.get(point.date)[row.key] = point.return_rate;
    });
  });

  return {
    chartData: [...chartByDate.values()].sort((left, right) => left.date.localeCompare(right.date)),
    commonStartDate,
    series: alignedSeries,
  };
}

export default function Comparison() {
  const [days, setDays] = useState(10);
  const cachePath = `/api/portfolio/benchmark-returns?days=${days}`;
  const cached = readApiCache(cachePath, { maxAgeMs: COMPARISON_CACHE_MS });
  const [data, setData] = useState(cached);
  const [enabled, setEnabled] = useState({});
  const [isLoading, setIsLoading] = useState(!cached);
  const [error, setError] = useState("");

  useEffect(() => {
    const fresh = isApiCacheFresh(cachePath, COMPARISON_CACHE_MS);
    if (fresh) {
      setData(readApiCache(cachePath, { maxAgeMs: COMPARISON_CACHE_MS }));
      return;
    }
    setIsLoading(true);
    api.portfolio
      .benchmarkReturns(days)
      .then((result) => {
        setData(result);
        setError("");
      })
      .catch((err) => setError(err.message))
      .finally(() => setIsLoading(false));
  }, [cachePath, days]);

  useEffect(() => {
    if (!data?.series?.length) return;
    setEnabled((current) => {
      const next = { ...current };
      data.series.forEach((row) => {
        if (!(row.key in next)) next[row.key] = true;
      });
      return next;
    });
  }, [data]);

  const visibleSeries = useMemo(
    () => (data?.series || []).filter((row) => enabled[row.key] !== false),
    [data, enabled],
  );

  const alignedComparison = useMemo(() => alignComparisonSeries(visibleSeries), [visibleSeries]);
  const { chartData, commonStartDate } = alignedComparison;

  const labelByKey = useMemo(
    () => Object.fromEntries((data?.series || []).map((row) => [row.key, row.label])),
    [data],
  );

  function toggleSeries(key) {
    setEnabled((current) => ({ ...current, [key]: current[key] === false }));
  }

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>수익률 비교</h1>
          <p>시장 지수, AlphaPilot 추천 성과, 실제 포트폴리오 수익률을 비교합니다.</p>
        </div>
      </header>

      {error && <p className="alert">{error}</p>}
      {isLoading && <Skeleton label={MESSAGES.loadingComparison} lines={4} />}

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>벤치마크 수익률</h2>
            <p>모든 표시 수익률에 실제 관측값이 있는 첫 공통 날짜부터 0%로 비교합니다.</p>
          </div>
          <div className="filter-row">
            {rangeOptions.map((option) => (
              <button
                className={days === option.value ? "active" : ""}
                key={option.value}
                type="button"
                onClick={() => setDays(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>

        <div className="benchmark-toggles">
          {(data?.series || []).map((row) => (
            <label className="checkbox-label" key={row.key}>
              <input
                checked={enabled[row.key] !== false}
                type="checkbox"
                onChange={() => toggleSeries(row.key)}
              />
              <span style={{ color: colorByKey[row.key] || "#334155" }}>{row.label}</span>
            </label>
          ))}
        </div>

        {!visibleSeries.length || chartData.length < 2 ? (
          <p className="empty-state">
            {visibleSeries.length && !commonStartDate
              ? "모든 표시 수익률에 공통으로 관측된 날짜가 아직 없습니다."
              : "표시할 수익률 데이터가 아직 없습니다."}
          </p>
        ) : (
          <div className="benchmark-recharts">
            <ResponsiveContainer height="100%" width="100%">
              <LineChart data={chartData} margin={{ top: 12, right: 16, bottom: 4, left: 0 }}>
                <CartesianGrid stroke="#e2e8f0" strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  minTickGap={28}
                  stroke="#64748b"
                  tick={{ fontSize: 12 }}
                  tickFormatter={(value) => String(value).slice(5)}
                />
                <YAxis
                  stroke="#64748b"
                  tick={{ fontSize: 12 }}
                  tickFormatter={(value) => `${value}%`}
                  width={52}
                />
                <Tooltip
                  formatter={(value, name) => [formatPercent(value), labelByKey[name] || name]}
                  labelFormatter={(label) => `날짜: ${label}`}
                />
                {visibleSeries.map((row) => (
                  <Line
                    activeDot={{ r: 4 }}
                    dataKey={row.key}
                    dot={false}
                    key={row.key}
                    name={row.key}
                    stroke={colorByKey[row.key] || "#334155"}
                    strokeWidth={2.5}
                    type="monotone"
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}

        <div className="metric-grid compact">
          {alignedComparison.series.map((row) => {
            const last = row.points[row.points.length - 1];
            return (
              <div key={row.key}>
                <span>{row.label}</span>
                <strong>{formatPercent(last?.return_rate)}</strong>
              </div>
            );
          })}
        </div>

        {!!data?.assumptions?.length && (
          <ul className="form-hint">
            {data.assumptions.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        )}
      </section>
    </section>
  );
}
