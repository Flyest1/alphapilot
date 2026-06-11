import { useEffect, useRef, useState } from "react";

import { api, isApiCacheFresh, readApiCache } from "../api/client.js";
import {
  dataLimitedCount,
  isTechnicalOnlyReport,
  pickReportWithStrategies,
  reportTypeLabel,
  splitStrategiesByAssets,
} from "../api/reports.js";
import PerformancePanel from "../components/reports/PerformancePanel.jsx";
import ReportContent from "../components/reports/ReportContent.jsx";
import ReportDiff from "../components/reports/ReportDiff.jsx";
import ReportSelector from "../components/reports/ReportSelector.jsx";
import StrategyFilters from "../components/reports/StrategyFilters.jsx";
import Skeleton from "../components/Skeleton.jsx";
import StrategyTable from "../components/StrategyTable.jsx";
import { HORIZON_LABELS, MESSAGES } from "../constants/strings.js";
import { findPreviousReport } from "../utils/reportDiff.js";
import { filterStrategies, sortStrategies } from "../utils/strategyFilters.js";

const REPORT_TYPES = ["domestic", "global"];
const REPORTS_CACHE_MS = 5 * 60 * 1000;
const INITIAL_HISTORY_COUNT = 2;
const REPORT_JOB_STORAGE_KEY = "alphapilot_active_report_job";
const REPORT_JOB_CLIENT_TIMEOUT_MS = 30 * 60 * 1000;
const activeJobStatuses = new Set(["queued", "running"]);

function firstReportForType(latest, reports, type) {
  return latest[type] || reports.find((report) => report.report_type === type) || null;
}

function readStoredReportJob() {
  try {
    const stored = window.localStorage.getItem(REPORT_JOB_STORAGE_KEY);
    if (!stored) return null;
    const job = JSON.parse(stored);
    if (!activeJobStatuses.has(job?.status) || isReportJobClientStale(job)) {
      window.localStorage.removeItem(REPORT_JOB_STORAGE_KEY);
      return null;
    }
    return job;
  } catch (_error) {
    return null;
  }
}

function writeStoredReportJob(job) {
  if (!job || !activeJobStatuses.has(job.status) || isReportJobClientStale(job)) {
    window.localStorage.removeItem(REPORT_JOB_STORAGE_KEY);
    return;
  }
  window.localStorage.setItem(REPORT_JOB_STORAGE_KEY, JSON.stringify(job));
}

function reportJobUpdatedAtMs(job) {
  const timestamp = job?.updated_at || job?.created_at;
  if (!timestamp) return Date.now();
  const parsed = new Date(timestamp).getTime();
  return Number.isNaN(parsed) ? Date.now() : parsed;
}

function isReportJobClientStale(job) {
  return Date.now() - reportJobUpdatedAtMs(job) > REPORT_JOB_CLIENT_TIMEOUT_MS;
}

function isActiveReportJob(job) {
  return activeJobStatuses.has(job?.status) && !isReportJobClientStale(job);
}

function reportJobMessage(job) {
  if (!job) return "";
  if (job.status === "queued") {
    return `${reportTypeLabel(job.report_type)} 리포트 생성 요청을 접수했습니다. 기존 리포트는 계속 볼 수 있습니다.`;
  }
  if (job.status === "running") {
    return `${reportTypeLabel(job.report_type)} 리포트를 생성하는 중입니다. 완료되면 자동으로 새로고침됩니다.`;
  }
  if (job.status === "completed") {
    return `${reportTypeLabel(job.report_type)} 리포트 생성이 완료되었습니다.`;
  }
  if (job.status === "failed") {
    return `${reportTypeLabel(job.report_type)} 리포트 생성에 실패했습니다.`;
  }
  return job.message || "";
}

export default function Reports() {
  const cachedLatest = readApiCache("/api/reports/latest", { maxAgeMs: REPORTS_CACHE_MS }) || {};
  const cachedReports = readApiCache("/api/reports", { maxAgeMs: REPORTS_CACHE_MS }) || [];
  const cachedAssets = readApiCache("/api/assets", { maxAgeMs: REPORTS_CACHE_MS }) || [];
  const cachedPerformanceLogs =
    readApiCache("/api/performance-logs", { maxAgeMs: REPORTS_CACHE_MS }) || [];
  const cachedRecommendationCycles =
    readApiCache("/api/recommendation-cycles", { maxAgeMs: REPORTS_CACHE_MS }) || [];
  const cachedSettings = readApiCache("/api/settings", { maxAgeMs: REPORTS_CACHE_MS });
  const cachedSelected = pickReportWithStrategies(cachedLatest) || cachedReports[0] || null;
  const hasCachedData = Boolean(cachedSelected || cachedReports.length || cachedAssets.length);
  const [latest, setLatest] = useState(cachedLatest);
  const [reports, setReports] = useState(cachedReports);
  const [assets, setAssets] = useState(cachedAssets);
  const [performanceLogs, setPerformanceLogs] = useState(cachedPerformanceLogs);
  const [recommendationCycles, setRecommendationCycles] = useState(cachedRecommendationCycles);
  const [settings, setSettings] = useState(cachedSettings);
  const [selected, setSelected] = useState(cachedSelected);
  const [activeType, setActiveType] = useState("domestic");
  const [strategyGroup, setStrategyGroup] = useState("owned");
  const [strategyFilter, setStrategyFilter] = useState("ALL");
  const [strategySort, setStrategySort] = useState("default");
  const [isLoading, setIsLoading] = useState(!hasCachedData);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [generationJob, setGenerationJob] = useState(readStoredReportJob);
  const [statusMessage, setStatusMessage] = useState("");
  const [error, setError] = useState("");
  const [historyCount, setHistoryCount] = useState(INITIAL_HISTORY_COUNT);
  const lastRefreshAt = useRef(0);
  const activeGenerationJob = isActiveReportJob(generationJob) ? generationJob : null;
  const generatingType = activeGenerationJob?.report_type || "";

  function loadReports({ background = false, preferredReportId = "" } = {}) {
    lastRefreshAt.current = Date.now();
    if (background) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    return Promise.all([
      api.reports.latest(),
      api.reports.list(),
      api.performanceLogs.list(),
      api.recommendationCycles.list(),
      api.assets.list(),
      api.settings.get(),
    ])
      .then(
        ([
          latestReports,
          reportList,
          performanceLogList,
          recommendationCycleList,
          assetList,
          appSettings,
        ]) => {
          const initialReport = pickReportWithStrategies(latestReports) || reportList[0] || null;
          setLatest(latestReports);
          setReports(reportList);
          setPerformanceLogs(performanceLogList);
          setRecommendationCycles(recommendationCycleList);
          setAssets(assetList);
          setSettings(appSettings);
          const preferredReport =
            preferredReportId && reportList.find((report) => report.id === preferredReportId);
          const nextReport =
            preferredReport ||
            (selected ? reportList.find((report) => report.id === selected.id) : null) ||
            initialReport;
          setSelected(nextReport);
          if (nextReport) setActiveType(nextReport.report_type);
        },
      )
      .catch((err) => setError(err.message))
      .finally(() => {
        setIsLoading(false);
        setIsRefreshing(false);
      });
  }

  useEffect(() => {
    const cacheFresh =
      isApiCacheFresh("/api/reports/latest", REPORTS_CACHE_MS) &&
      isApiCacheFresh("/api/reports", REPORTS_CACHE_MS) &&
      isApiCacheFresh("/api/recommendation-cycles", REPORTS_CACHE_MS) &&
      isApiCacheFresh("/api/assets", REPORTS_CACHE_MS) &&
      isApiCacheFresh("/api/settings", REPORTS_CACHE_MS);
    if (!cacheFresh) {
      loadReports({ background: hasCachedData });
    }

    function refreshOnReturn() {
      if (!document.hidden && Date.now() - lastRefreshAt.current > REPORTS_CACHE_MS) {
        loadReports({ background: true });
      }
    }

    window.addEventListener("focus", refreshOnReturn);
    document.addEventListener("visibilitychange", refreshOnReturn);
    return () => {
      window.removeEventListener("focus", refreshOnReturn);
      document.removeEventListener("visibilitychange", refreshOnReturn);
    };
  }, []);

  useEffect(() => {
    if (!isActiveReportJob(generationJob)) return undefined;

    let cancelled = false;
    async function checkReportJob() {
      try {
        const job = await api.reports.jobStatus(generationJob.job_id);
        if (cancelled) return;
        setGenerationJob(job);
        writeStoredReportJob(job);
        if (job.status === "completed") {
          setStatusMessage(reportJobMessage(job));
          await loadReports({ background: true, preferredReportId: job.report_id });
          if (!cancelled) {
            setGenerationJob(null);
            writeStoredReportJob(null);
          }
        } else if (job.status === "failed") {
          setError(job.message || "리포트 생성에 실패했습니다.");
          setGenerationJob(null);
          writeStoredReportJob(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
          if (isReportJobClientStale(generationJob)) {
            setGenerationJob(null);
            writeStoredReportJob(null);
          }
        }
      }
    }

    checkReportJob();
    const intervalId = window.setInterval(checkReportJob, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [generationJob?.job_id]);

  const content = selected?.content || {};
  const filteredReports = reports.filter((report) => report.report_type === activeType);
  const visibleReports = filteredReports.slice(0, historyCount);
  const candidateHorizonLabel = HORIZON_LABELS[settings?.candidate_horizon] || "중기 20거래일";
  const strategies = content.asset_strategies || [];
  const { ownedStrategies, candidateStrategies } = splitStrategiesByAssets(strategies, assets);
  const latestSplit = splitStrategiesByAssets(
    latest[activeType]?.content?.asset_strategies || [],
    assets,
  );
  const selectedStrategyGroup =
    strategyGroup === "candidates" ? candidateStrategies : ownedStrategies;
  const filteredStrategies = sortStrategies(
    filterStrategies(selectedStrategyGroup, strategyFilter),
    strategySort,
    performanceLogs,
  );
  const previousReport = findPreviousReport(selected, reports);
  const selectedTickers = new Set(strategies.map((strategy) => strategy.ticker));
  const selectedPerformanceLogs = performanceLogs.filter((row) => selectedTickers.has(row.ticker));
  const selectedRecommendationCycles = recommendationCycles.filter((row) =>
    selectedTickers.has(row.ticker),
  );

  function selectType(type) {
    setActiveType(type);
    setHistoryCount(INITIAL_HISTORY_COUNT);
    setSelected(firstReportForType(latest, reports, type));
  }

  async function generateManualReport(type) {
    const confirmed = window.confirm(
      `${reportTypeLabel(type)} 리포트를 생성할까요? 외부 시세, 뉴스, OpenAI 호출 때문에 시간이 걸릴 수 있습니다.`,
    );
    if (!confirmed) return;
    setError("");
    setStatusMessage("");
    try {
      const job = await api.reports.generate(type);
      setGenerationJob(job);
      writeStoredReportJob(job);
      setActiveType(type);
    } catch (err) {
      setError(err.message);
    }
  }

  function clearGenerationStatus() {
    setGenerationJob(null);
    setStatusMessage("");
    writeStoredReportJob(null);
  }

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>리포트</h1>
          <p>국내/글로벌 시장 리포트와 자산별 리스크 관리 전략을 확인합니다.</p>
        </div>
        <div className="header-actions">
          {REPORT_TYPES.map((type) => (
            <button
              disabled={Boolean(generatingType)}
              key={type}
              type="button"
              onClick={() => generateManualReport(type)}
            >
              {generatingType === type
                ? `${reportTypeLabel(type)} 생성 중`
                : `${reportTypeLabel(type)} 리포트 생성`}
            </button>
          ))}
        </div>
      </header>
      {error && (
        <div className="notice notice-with-action">
          <span className="alert">{error}</span>
          <button type="button" onClick={() => loadReports()}>
            다시 시도
          </button>
        </div>
      )}
      {statusMessage && <p className="notice">{statusMessage}</p>}
      {activeGenerationJob && (
        <div className="notice notice-with-action">
          <span>{reportJobMessage(activeGenerationJob)}</span>
          <button type="button" onClick={clearGenerationStatus}>
            생성 상태 초기화
          </button>
        </div>
      )}
      {isLoading && <Skeleton label={MESSAGES.loadingReports} lines={4} />}
      {isRefreshing && <p className="field-hint">{MESSAGES.refreshing}</p>}

      <ReportSelector
        activeType={activeType}
        filteredReports={filteredReports}
        isLoading={isLoading}
        latest={latest}
        latestSplit={latestSplit}
        selected={selected}
        visibleReports={visibleReports}
        onSelectReport={setSelected}
        onSelectType={selectType}
        onShowMore={() => setHistoryCount((current) => current + INITIAL_HISTORY_COUNT)}
      />

      <ReportContent
        candidateCount={candidateStrategies.length}
        dataLimitedCountValue={dataLimitedCount(selected)}
        ownedCount={ownedStrategies.length}
        performanceLogs={performanceLogs}
        selected={selected}
        technicalOnly={isTechnicalOnlyReport(selected)}
      />

      <ReportDiff previous={previousReport} selected={selected} />

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>자산별 전략</h2>
            <p>추가 후보는 {candidateHorizonLabel} 목표 기준으로 선별합니다.</p>
          </div>
          <div className="inline-metrics">
            <span>{ownedStrategies.length}개 보유</span>
            <span>{candidateStrategies.length}개 후보</span>
          </div>
        </div>
        {isLoading ? (
          <Skeleton label={MESSAGES.loadingStrategies} />
        ) : (
          <>
            <StrategyFilters
              strategyFilter={strategyFilter}
              strategyGroup={strategyGroup}
              strategySort={strategySort}
              onFilterChange={setStrategyFilter}
              onGroupChange={setStrategyGroup}
              onSortChange={setStrategySort}
            />
            <StrategyTable
              inputsByTicker={selected?.report_inputs?.tickers}
              performanceLogs={performanceLogs}
              strategies={filteredStrategies}
            />
          </>
        )}
      </section>

      <PerformancePanel
        cycles={selectedRecommendationCycles}
        isLoading={isLoading}
        logs={selectedPerformanceLogs}
      />
    </section>
  );
}
