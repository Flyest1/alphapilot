import { useEffect, useState } from "react";

import { api, isApiCacheFresh, readApiCache } from "../api/client.js";
import Skeleton from "../components/Skeleton.jsx";
import SummaryCard from "../components/SummaryCard.jsx";
import { MESSAGES } from "../constants/strings.js";
import { formatReturn } from "../utils/formatters.js";
import { groupTitle, statsHeadlines } from "../utils/recommendationStats.js";

const STATS_CACHE_MS = 5 * 60 * 1000;
const STATS_PATH = "/api/recommendation-stats";

function formatWinRate(value) {
  if (value == null) return "-";
  return `${Math.round(Number(value) * 100)}%`;
}

function formatDays(value) {
  if (value == null) return "-";
  return `${Number(value).toFixed(1)}일`;
}

export default function Performance() {
  const cached = readApiCache(STATS_PATH, { maxAgeMs: STATS_CACHE_MS });
  const [stats, setStats] = useState(cached);
  const [isLoading, setIsLoading] = useState(!cached);
  const [error, setError] = useState("");

  function loadStats() {
    setIsLoading(true);
    api.recommendationStats
      .get()
      .then((result) => {
        setStats(result);
        setError("");
      })
      .catch((err) => setError(err.message))
      .finally(() => setIsLoading(false));
  }

  useEffect(() => {
    if (!isApiCacheFresh(STATS_PATH, STATS_CACHE_MS)) {
      loadStats();
    }
  }, []);

  const totals = stats?.totals || {};
  const groups = stats?.groups || [];
  const headlines = statsHeadlines(stats);
  const minSample = stats?.min_sample_for_calibration ?? 30;

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>성과 분석</h1>
          <p>액션·기간·점수밴드별 추천 실측 성과와 신뢰도 보정 상태를 확인합니다.</p>
        </div>
        <div className="header-actions">
          <button disabled={isLoading} type="button" onClick={loadStats}>
            새로고침
          </button>
        </div>
      </header>

      {error && (
        <div className="notice notice-with-action">
          <span className="alert">{error}</span>
          <button type="button" onClick={loadStats}>
            다시 시도
          </button>
        </div>
      )}
      {isLoading && <Skeleton label={MESSAGES.loadingStats} lines={4} />}

      <div className="summary-grid">
        <SummaryCard label="전체 추천 cycle" value={totals.cycle_count ?? 0} />
        <SummaryCard label="종료된 cycle" value={totals.closed_count ?? 0} />
        <SummaryCard label="목표 도달" value={totals.win_count ?? 0} />
        <SummaryCard label="전체 승률" value={formatWinRate(totals.win_rate)} />
      </div>

      <section className="panel">
        <h2>핵심 요약</h2>
        {headlines.length === 0 ? (
          <p className="empty-state">
            아직 종료 표본이 부족합니다. 추천 cycle이 목표/손절/만료로 종료되면 승률이 집계됩니다.
          </p>
        ) : (
          <ul>
            {headlines.map((headline) => (
              <li key={headline.key}>{headline.text}</li>
            ))}
          </ul>
        )}
        <p className="field-hint">
          종료 표본이 {minSample}건 이상인 그룹은 리포트 신뢰도에 실측 승률 보정계수가 곱해집니다.
          과거 성과는 미래 수익을 보장하지 않습니다.
        </p>
      </section>

      <section className="panel">
        <h2>그룹별 실측 성과</h2>
        {!isLoading && groups.length === 0 && (
          <p className="empty-state">집계할 추천 cycle 데이터가 아직 없습니다.</p>
        )}
        {groups.length > 0 && (
          <div className="table-wrap performance-table">
            <table>
              <thead>
                <tr>
                  <th>그룹</th>
                  <th>전체</th>
                  <th>종료</th>
                  <th>승률</th>
                  <th>평균 5일</th>
                  <th>평균 20일</th>
                  <th>평균 보유일</th>
                  <th>신뢰도 보정</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((group) => (
                  <tr key={`${group.action}-${group.horizon}-${group.score_band}`}>
                    <td>{groupTitle(group)}</td>
                    <td>{group.cycle_count}</td>
                    <td>{group.closed_count}</td>
                    <td>{formatWinRate(group.win_rate)}</td>
                    <td>{formatReturn(group.avg_return_5d)}</td>
                    <td>{formatReturn(group.avg_return_20d)}</td>
                    <td>{formatDays(group.avg_holding_days)}</td>
                    <td>
                      {group.calibration_applied ? (
                        <span className="status-pill ok">적용 ×{group.calibration_factor}</span>
                      ) : (
                        <span className="status-pill warning">표본 부족</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}
