import { useEffect, useState } from "react";

import { api, readApiCache } from "../api/client.js";
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
import StrategyTable from "../components/StrategyTable.jsx";
import SummaryCard from "../components/SummaryCard.jsx";

function money(value) {
  return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export default function Dashboard() {
  const cachedSummary = readApiCache("/api/portfolio/summary");
  const cachedLatest = readApiCache("/api/reports/latest");
  const cachedAssets = readApiCache("/api/assets");
  const hasCachedData = Boolean(cachedSummary || cachedLatest || cachedAssets);
  const [summary, setSummary] = useState(cachedSummary);
  const [latest, setLatest] = useState(cachedLatest);
  const [assets, setAssets] = useState(cachedAssets || []);
  const [isLoading, setIsLoading] = useState(!hasCachedData);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState("");

  function loadDashboard({ background = false } = {}) {
    if (background) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    Promise.all([api.portfolio.summary(), api.reports.latest(), api.assets.list()])
      .then(([portfolio, reports, assetList]) => {
        setSummary(portfolio);
        setLatest(reports);
        setAssets(assetList);
      })
      .catch((err) => setError(err.message))
      .finally(() => {
        setIsLoading(false);
        setIsRefreshing(false);
      });
  }

  useEffect(() => {
    loadDashboard({ background: hasCachedData });

    function refreshOnReturn() {
      if (!document.hidden) loadDashboard({ background: true });
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
  const topStrategies = [...ownedStrategies]
    .sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
    .slice(0, 5);
  const topCandidates = [...candidateStrategies]
    .sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
    .slice(0, 5);

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>포트폴리오 대시보드</h1>
          <p>보유 자산, 최신 리포트, 전략 신호를 한눈에 확인합니다.</p>
        </div>
      </header>

      {error && <p className="alert">{error}</p>}
      {isLoading && <p className="empty-state">포트폴리오 데이터를 불러오는 중입니다.</p>}
      {isRefreshing && <p className="field-hint">최신 데이터를 확인하는 중입니다.</p>}

      <div className="summary-grid">
        <SummaryCard label="총 평가금액" value={money(summary?.total_market_value)} />
        <SummaryCard
          label="평가손익"
          value={money(summary?.total_profit_loss)}
          tone={summary?.total_profit_loss >= 0 ? "positive" : "negative"}
        />
        <SummaryCard
          label="수익률"
          value={`${summary?.total_return_rate ?? 0}%`}
          tone={summary?.total_return_rate >= 0 ? "positive" : "negative"}
        />
        <SummaryCard label="현금" value={money(summary?.cash_value)} />
      </div>

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
        <div className="top-strategy-list">
          {topStrategies.length === 0 && <p className="empty-state">표시할 최신 전략이 없습니다.</p>}
          {topStrategies.map((strategy) => (
            <div className="top-strategy-row" key={`${strategy.ticker}-${strategy.action}`}>
              <div>
                <strong>{strategy.ticker}</strong>
                <span>{strategy.name}</span>
              </div>
              <span className={`badge ${strategy.action.toLowerCase()}`}>
                {actionLabel(strategy.action)}
              </span>
              <span>{strategy.confidence}%</span>
            </div>
          ))}
        </div>
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
        <div className="top-strategy-list">
          {topCandidates.length === 0 && (
            <p className="empty-state">현재 표시할 추가 매수 후보가 없습니다.</p>
          )}
          {topCandidates.map((strategy) => (
            <div className="top-strategy-row" key={`${strategy.ticker}-${strategy.action}`}>
              <div>
                <strong>{strategy.ticker}</strong>
                <span>{strategy.name}</span>
              </div>
              <span className={`badge ${strategy.action.toLowerCase()}`}>
                {actionLabel(strategy.action)}
              </span>
              <span>{strategy.confidence}%</span>
            </div>
          ))}
        </div>
      </section>

      <div className="content-grid">
        <section className="panel">
          <h2>자산 비중</h2>
          <div className="bars">
            {(summary?.asset_allocation || []).map((asset) => (
              <div className="bar-row" key={asset.ticker}>
                <div>
                  <strong>{asset.ticker}</strong>
                  <span>{asset.name}</span>
                </div>
                <div className="bar-track">
                  <span style={{ width: `${Math.min(asset.weight, 100)}%` }} />
                </div>
                <em>{asset.weight}%</em>
              </div>
            ))}
          </div>
        </section>

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
          <p className="empty-state">전략을 불러오는 중입니다.</p>
        ) : (
          <StrategyTable strategies={ownedStrategies} />
        )}
      </section>
    </section>
  );
}
