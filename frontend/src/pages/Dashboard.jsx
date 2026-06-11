import { useEffect, useRef, useState } from "react";

import { api, isApiCacheFresh, readApiCache } from "../api/client.js";
import {
  actionLabel,
  dataLimitedCount,
  displayText,
  formatReportTime,
  pickReportWithStrategies,
  reportAiModeLabel,
  reportTypeLabel,
  splitStrategiesByAssets,
} from "../api/reports.js";
import ActionBriefing from "../components/dashboard/ActionBriefing.jsx";
import AllocationChart from "../components/dashboard/AllocationChart.jsx";
import ExposurePanel from "../components/dashboard/ExposurePanel.jsx";
import RebalanceCard from "../components/dashboard/RebalanceCard.jsx";
import SummaryCards from "../components/dashboard/SummaryCards.jsx";
import TopStrategies from "../components/dashboard/TopStrategies.jsx";
import TrendChart from "../components/dashboard/TrendChart.jsx";
import KeyMessageList from "../components/KeyMessageList.jsx";
import Skeleton from "../components/Skeleton.jsx";
import StrategyTable from "../components/StrategyTable.jsx";
import { MESSAGES } from "../constants/strings.js";

const DASHBOARD_CACHE_MS = 5 * 60 * 1000;

export default function Dashboard() {
  const cachedSummary = readApiCache("/api/portfolio/summary", { maxAgeMs: DASHBOARD_CACHE_MS });
  const cachedLatest = readApiCache("/api/reports/latest", { maxAgeMs: DASHBOARD_CACHE_MS });
  const cachedAssets = readApiCache("/api/assets", { maxAgeMs: DASHBOARD_CACHE_MS });
  const cachedPerformanceLogs =
    readApiCache("/api/performance-logs", { maxAgeMs: DASHBOARD_CACHE_MS }) || [];
  const cachedCycles =
    readApiCache("/api/recommendation-cycles", { maxAgeMs: DASHBOARD_CACHE_MS }) || [];
  const hasCachedData = Boolean(cachedSummary || cachedLatest || cachedAssets);
  const [summary, setSummary] = useState(cachedSummary);
  const [latest, setLatest] = useState(cachedLatest);
  const [assets, setAssets] = useState(cachedAssets || []);
  const [performanceLogs, setPerformanceLogs] = useState(cachedPerformanceLogs);
  const [recommendationCycles, setRecommendationCycles] = useState(cachedCycles);
  const [isLoading, setIsLoading] = useState(!hasCachedData);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [snapshotStatus, setSnapshotStatus] = useState("");
  const [chartRange, setChartRange] = useState("7d");
  const lastRefreshAt = useRef(0);

  function loadDashboard({ background = false } = {}) {
    lastRefreshAt.current = Date.now();
    if (background) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    return Promise.all([
      api.portfolio.summary(),
      api.reports.latest(),
      api.assets.list(),
      api.performanceLogs.list(),
      api.recommendationCycles.list(),
    ])
      .then(([portfolio, reports, assetList, performanceLogList, cycleList]) => {
        setSummary(portfolio);
        setLatest(reports);
        setAssets(assetList);
        setPerformanceLogs(performanceLogList);
        setRecommendationCycles(cycleList);
        setError("");
      })
      .catch((err) => setError(err.message))
      .finally(() => {
        setIsLoading(false);
        setIsRefreshing(false);
      });
  }

  async function createSnapshot() {
    setError("");
    setSnapshotStatus("");
    setIsRefreshing(true);
    try {
      const result = await api.portfolio.snapshot();
      setSummary(result.summary);
      setSnapshotStatus("현재 환율과 시세 기준으로 자산 스냅샷을 저장했습니다.");
      await loadDashboard({ background: true });
    } catch (err) {
      setError(err.message);
    } finally {
      setIsRefreshing(false);
    }
  }

  useEffect(() => {
    const cacheFresh =
      isApiCacheFresh("/api/portfolio/summary", DASHBOARD_CACHE_MS) &&
      isApiCacheFresh("/api/reports/latest", DASHBOARD_CACHE_MS) &&
      isApiCacheFresh("/api/assets", DASHBOARD_CACHE_MS) &&
      isApiCacheFresh("/api/performance-logs", DASHBOARD_CACHE_MS);
    if (!cacheFresh) {
      loadDashboard({ background: hasCachedData });
    }

    function refreshOnReturn() {
      if (!document.hidden && Date.now() - lastRefreshAt.current > DASHBOARD_CACHE_MS) {
        loadDashboard({ background: true });
      }
    }

    window.addEventListener("focus", refreshOnReturn);
    document.addEventListener("visibilitychange", refreshOnReturn);
    return () => {
      window.removeEventListener("focus", refreshOnReturn);
      document.removeEventListener("visibilitychange", refreshOnReturn);
    };
  }, []);

  const report = pickReportWithStrategies(latest);
  const content = report?.content || {};
  const strategies = content.asset_strategies || [];
  const { ownedStrategies, candidateStrategies } = splitStrategiesByAssets(strategies, assets);
  const actionCounts = ["BUY", "HOLD", "REDUCE", "SELL", "WATCH"].map((action) => ({
    action,
    count: ownedStrategies.filter((strategy) => strategy.action === action).length,
  }));

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>포트폴리오 대시보드</h1>
          <p>보유 자산, 최신 리포트, 전략 신호를 한눈에 확인합니다.</p>
        </div>
        <div className="header-actions">
          <button disabled={isRefreshing} type="button" onClick={createSnapshot}>
            자산 스냅샷 저장
          </button>
        </div>
      </header>

      {error && (
        <div className="notice notice-with-action">
          <span className="alert">{error}</span>
          <button type="button" onClick={() => loadDashboard()}>
            다시 시도
          </button>
        </div>
      )}
      {snapshotStatus && <p className="notice">{snapshotStatus}</p>}
      {isLoading && <Skeleton label={MESSAGES.loadingDashboard} lines={4} />}
      {isRefreshing && <p className="field-hint">{MESSAGES.refreshing}</p>}

      <ActionBriefing
        assets={assets}
        cycles={recommendationCycles}
        report={report}
        summary={summary}
      />

      <SummaryCards summary={summary} />

      <RebalanceCard summary={summary} />

      <ExposurePanel summary={summary} />

      <TrendChart chartRange={chartRange} summary={summary} onChangeRange={setChartRange} />

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>최신 전략 요약</h2>
            <p>
              {report
                ? `${reportTypeLabel(report.report_type)} 리포트 · ${formatReportTime(report.created_at)}`
                : "생성된 리포트가 없습니다."}
            </p>
          </div>
          <div className="inline-metrics">
            <span>{ownedStrategies.length}개 보유 전략</span>
            <span>{candidateStrategies.length}개 추가 후보</span>
            <span>{dataLimitedCount(report)}개 데이터 제한</span>
            <span>{reportAiModeLabel(report)}</span>
          </div>
        </div>
        <div className="action-summary-grid">
          {actionCounts.map((item) => (
            <div key={item.action}>
              <span>{actionLabel(item.action)}</span>
              <strong>{item.count}</strong>
            </div>
          ))}
        </div>
        <div className="key-message-panel">
          <h3>핵심 매매 메시지</h3>
          <KeyMessageList limit={6} performanceLogs={performanceLogs} strategies={strategies} />
        </div>
        <TopStrategies emptyMessage="표시할 최신 전략이 없습니다." strategies={ownedStrategies} />
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>추가 매수 후보</h2>
            <p>보유 자산이 아닌 후보군 중 기술 점수가 높은 항목입니다.</p>
          </div>
          <div className="inline-metrics">
            <span>{candidateStrategies.length}개 후보</span>
          </div>
        </div>
        <TopStrategies
          emptyMessage="현재 표시할 추가 매수 후보가 없습니다."
          strategies={candidateStrategies}
        />
      </section>

      <div className="content-grid">
        <AllocationChart allocation={summary?.asset_allocation || []} />

        <section className="panel">
          <h2>최신 리포트</h2>
          <p>
            {displayText(content.market_summary?.summary || summary?.latest_report_summary) ||
              "아직 리포트가 없습니다."}
          </p>
          <h3>기회 요인</h3>
          <ul>
            {(content.opportunities || []).slice(0, 4).map((item) => (
              <li key={item}>{displayText(item)}</li>
            ))}
          </ul>
          <h3>주요 위험</h3>
          <ul>
            {(content.key_risks || []).slice(0, 4).map((item) => (
              <li key={item}>{displayText(item)}</li>
            ))}
          </ul>
        </section>
      </div>

      <section className="panel">
        <h2>자산별 전략</h2>
        {isLoading ? (
          <Skeleton label={MESSAGES.loadingStrategies} />
        ) : (
          <StrategyTable
            inputsByTicker={report?.report_inputs?.tickers}
            performanceLogs={performanceLogs}
            strategies={ownedStrategies}
          />
        )}
      </section>
    </section>
  );
}
