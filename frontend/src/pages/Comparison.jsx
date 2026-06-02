import { useEffect, useMemo, useState } from "react";

import { api, isApiCacheFresh, readApiCache } from "../api/client.js";

const colorByKey = {
  kospi: "#0f766e",
  kosdaq: "#2563eb",
  sp500: "#7c3aed",
  nasdaq: "#ea580c",
  alphapilot: "#be123c",
  actual_portfolio: "#111827",
};

const rangeOptions = [
  { label: "30일", value: 30 },
  { label: "60일", value: 60 },
  { label: "120일", value: 120 },
];

function formatPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "-";
  return `${numeric.toFixed(2)}%`;
}

function benchmarkPath(points, dateIndex, minReturn, returnRange) {
  const width = 760;
  const height = 300;
  const left = 42;
  const right = 18;
  const top = 18;
  const bottom = 32;
  const xRange = width - left - right;
  const yRange = height - top - bottom;
  const maxIndex = Math.max(dateIndex.size - 1, 1);
  return points
    .map((point) => {
      const index = dateIndex.get(point.date) ?? 0;
      const x = left + (index / maxIndex) * xRange;
      const y = top + ((Number(point.return_rate) - minReturn) / returnRange) * -yRange + yRange;
      return { ...point, x, y };
    })
    .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
}

export default function Comparison() {
  const [days, setDays] = useState(60);
  const cachePath = `/api/portfolio/benchmark-returns?days=${days}`;
  const cached = readApiCache(cachePath, { maxAgeMs: 5 * 60 * 1000 });
  const [data, setData] = useState(cached);
  const [enabled, setEnabled] = useState({});
  const [hovered, setHovered] = useState(null);
  const [isLoading, setIsLoading] = useState(!cached);
  const [error, setError] = useState("");

  useEffect(() => {
    const fresh = isApiCacheFresh(cachePath, 5 * 60 * 1000);
    if (fresh) {
      setData(readApiCache(cachePath, { maxAgeMs: 5 * 60 * 1000 }));
      return;
    }
    setIsLoading(true);
    api.portfolio
      .benchmarkReturns(days)
      .then((result) => {
        setData(result);
        setEnabled((current) => {
          if (Object.keys(current).length) return current;
          return Object.fromEntries((result.series || []).map((row) => [row.key, true]));
        });
      })
      .catch((err) => setError(err.message))
      .finally(() => setIsLoading(false));
  }, [days]);

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

  const chart = useMemo(() => {
    const visibleSeries = (data?.series || []).filter((row) => enabled[row.key] !== false);
    const dates = Array.from(
      new Set(visibleSeries.flatMap((row) => row.points.map((point) => point.date))),
    ).sort();
    const values = visibleSeries.flatMap((row) =>
      row.points.map((point) => Number(point.return_rate)),
    );
    const minReturn = Math.min(...values, 0);
    const maxReturn = Math.max(...values, 0);
    const returnRange = Math.max(maxReturn - minReturn, 1);
    const dateIndex = new Map(dates.map((date, index) => [date, index]));
    return {
      dates,
      maxReturn,
      minReturn,
      returnRange,
      visibleSeries,
      paths: visibleSeries.map((row) => ({
        ...row,
        pathPoints: benchmarkPath(row.points, dateIndex, minReturn, returnRange),
      })),
    };
  }, [data, enabled]);

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
      {isLoading && <p className="empty-state">비교 데이터를 불러오는 중입니다.</p>}

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>벤치마크 수익률</h2>
            <p>x축은 날짜, y축은 시작일 대비 누적 수익률입니다.</p>
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

        {!chart.visibleSeries.length ? (
          <p className="empty-state">표시할 수익률 데이터가 아직 없습니다.</p>
        ) : (
          <div className="benchmark-chart-wrap">
            <svg className="benchmark-chart" role="img" viewBox="0 0 760 300">
              <line className="chart-axis" x1="42" x2="742" y1="268" y2="268" />
              <line className="chart-axis" x1="42" x2="42" y1="18" y2="268" />
              <text className="chart-label" x="44" y="28">
                {formatPercent(chart.maxReturn)}
              </text>
              <text className="chart-label" x="44" y="264">
                {formatPercent(chart.minReturn)}
              </text>
              {chart.paths.map((row) => (
                <g key={row.key}>
                  <polyline
                    fill="none"
                    points={row.pathPoints.map((point) => `${point.x},${point.y}`).join(" ")}
                    stroke={colorByKey[row.key] || "#334155"}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="2.5"
                  />
                  {row.pathPoints.map((point) => (
                    <circle
                      cx={point.x}
                      cy={point.y}
                      fill={colorByKey[row.key] || "#334155"}
                      key={`${row.key}-${point.date}`}
                      r="4"
                      onMouseEnter={() =>
                        setHovered({
                          date: point.date,
                          label: row.label,
                          return_rate: point.return_rate,
                        })
                      }
                      onMouseLeave={() => setHovered(null)}
                    />
                  ))}
                </g>
              ))}
            </svg>
            {hovered && (
              <div className="chart-tooltip">
                <strong>{hovered.label}</strong>
                <span>{hovered.date}</span>
                <em>{formatPercent(hovered.return_rate)}</em>
              </div>
            )}
          </div>
        )}

        <div className="metric-grid compact">
          {chart.visibleSeries.map((row) => {
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
