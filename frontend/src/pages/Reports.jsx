import { useEffect, useState } from "react";

import { api } from "../api/client.js";
import {
  actionLabel,
  dataLimitedCount,
  displayText,
  formatReportTime,
  isTechnicalOnlyReport,
  pickReportWithStrategies,
  reportAiModeLabel,
  reportTitle,
  reportTypeLabel,
  splitStrategiesByAssets,
  strategyCount,
  trendLabel,
} from "../api/reports.js";
import StrategyTable from "../components/StrategyTable.jsx";

const reportTypes = ["domestic", "global"];
const strategyFilters = ["ALL", "BUY", "HOLD", "REDUCE", "SELL", "WATCH", "DATA_LIMITED"];
const filterLabels = {
  ALL: "전체",
  BUY: "매수",
  HOLD: "보유",
  REDUCE: "축소",
  SELL: "매도",
  WATCH: "관찰",
  DATA_LIMITED: "데이터 제한",
};

function firstReportForType(latest, reports, type) {
  return latest[type] || reports.find((report) => report.report_type === type) || null;
}

export default function Reports() {
  const [latest, setLatest] = useState({});
  const [reports, setReports] = useState([]);
  const [assets, setAssets] = useState([]);
  const [performanceLogs, setPerformanceLogs] = useState([]);
  const [selected, setSelected] = useState(null);
  const [activeType, setActiveType] = useState("domestic");
  const [strategyFilter, setStrategyFilter] = useState("ALL");
  const [isLoading, setIsLoading] = useState(true);
  const [generatingType, setGeneratingType] = useState("");
  const [statusMessage, setStatusMessage] = useState("");
  const [error, setError] = useState("");

  function loadReports() {
    setIsLoading(true);
    return Promise.all([
      api.reports.latest(),
      api.reports.list(),
      api.performanceLogs.list(),
      api.assets.list(),
    ])
      .then(([latestReports, reportList, performanceLogList, assetList]) => {
        const initialReport = pickReportWithStrategies(latestReports) || reportList[0] || null;
        setLatest(latestReports);
        setReports(reportList);
        setPerformanceLogs(performanceLogList);
        setAssets(assetList);
        const nextReport = selected
          ? reportList.find((report) => report.id === selected.id) || initialReport
          : initialReport;
        setSelected(nextReport);
        if (nextReport) setActiveType(nextReport.report_type);
      })
      .catch((err) => setError(err.message))
      .finally(() => setIsLoading(false));
  }

  useEffect(() => {
    loadReports();
  }, []);

  const content = selected?.content || {};
  const filteredReports = reports.filter((report) => report.report_type === activeType);
  const latestForActiveType = latest[activeType];
  const selectedDataLimitedCount = dataLimitedCount(selected);
  const selectedTechnicalOnly = isTechnicalOnlyReport(selected);
  const strategies = content.asset_strategies || [];
  const { ownedStrategies, candidateStrategies } = splitStrategiesByAssets(strategies, assets);
  const latestSplit = splitStrategiesByAssets(
    latestForActiveType?.content?.asset_strategies || [],
    assets,
  );
  const filteredStrategies = ownedStrategies.filter((strategy) => {
    if (strategyFilter === "ALL") return true;
    if (strategyFilter === "DATA_LIMITED") return strategy.reasoning === "data-limited";
    return strategy.action === strategyFilter;
  });
  const selectedPerformanceLogs = performanceLogs.filter((row) => row.report_id === selected?.id);

  function selectType(type) {
    setActiveType(type);
    setSelected(firstReportForType(latest, reports, type));
  }

  async function generateManualReport(type) {
    setError("");
    setStatusMessage("");
    setGeneratingType(type);
    try {
      const generated = await api.reports.generate(type);
      setStatusMessage(`${reportTypeLabel(type)} 리포트를 생성했습니다.`);
      await loadReports();
      setSelected(generated);
      setActiveType(type);
    } catch (err) {
      setError(err.message);
    } finally {
      setGeneratingType("");
    }
  }

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>리포트</h1>
          <p>국내/글로벌 시장 리포트와 자산별 리스크 관리 전략을 확인합니다.</p>
        </div>
        <div className="header-actions">
          {reportTypes.map((type) => (
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
      {error && <p className="alert">{error}</p>}
      {statusMessage && <p className="notice">{statusMessage}</p>}
      {isLoading && <p className="empty-state">리포트를 불러오는 중입니다.</p>}

      <div className="segmented-control">
        {reportTypes.map((type) => (
          <button
            className={activeType === type ? "active" : ""}
            key={type}
            type="button"
            onClick={() => selectType(type)}
          >
            <strong>{reportTypeLabel(type)}</strong>
            <span>{strategyCount(latest[type])}개 전략</span>
          </button>
        ))}
      </div>

      <div className="content-grid">
        <section className="panel">
          <h2>최신 {reportTypeLabel(activeType)} 리포트</h2>
          <div className="metric-grid compact">
            <div>
              <span>생성 시간</span>
              <strong>{formatReportTime(latestForActiveType?.created_at)}</strong>
            </div>
            <div>
              <span>보유 전략</span>
              <strong>{latestSplit.ownedStrategies.length}</strong>
            </div>
            <div>
              <span>추가 후보</span>
              <strong>{latestSplit.candidateStrategies.length}</strong>
            </div>
            <div>
              <span>데이터 제한</span>
              <strong>{dataLimitedCount(latestForActiveType)}</strong>
            </div>
            <div>
              <span>AI 모드</span>
              <strong>{reportAiModeLabel(latestForActiveType)}</strong>
            </div>
          </div>
        </section>

        <section className="panel">
          <h2>{reportTypeLabel(activeType)} 리포트 이력</h2>
          <div className="report-list">
            {!isLoading && filteredReports.length === 0 && (
              <p className="empty-state">아직 생성된 리포트가 없습니다.</p>
            )}
            {filteredReports.map((report) => (
              <button
                className={selected?.id === report.id ? "active" : ""}
                key={report.id}
                type="button"
                onClick={() => setSelected(report)}
              >
                <strong>{reportTitle(report)}</strong>
                <span>
                  {formatReportTime(report.created_at)} · {strategyCount(report)}개 전략
                </span>
              </button>
            ))}
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>{reportTitle(selected)}</h2>
            <p>{formatReportTime(selected?.created_at)}</p>
          </div>
          <div className="inline-metrics">
            <span>{ownedStrategies.length}개 보유 전략</span>
            <span>{candidateStrategies.length}개 추가 후보</span>
            <span>{selectedDataLimitedCount}개 데이터 제한</span>
            {selectedTechnicalOnly && <span>기술 지표만</span>}
          </div>
        </div>
        <p>{displayText(content.market_summary?.summary) || "표시할 리포트 내용이 없습니다."}</p>
        {!!content.market_summary?.key_indices?.length && (
          <div className="index-list">
            {content.market_summary.key_indices.map((index) => (
              <span key={index.name || JSON.stringify(index)}>
                {index.name}: {index.technical_score ?? "-"} {trendLabel(index.trend_label)}
              </span>
            ))}
          </div>
        )}
        <div className="risk-grid">
          <div>
            <h3>기회 요인</h3>
            <ul>
              {(content.opportunities || []).map((item) => (
                <li key={item}>{displayText(item)}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3>주요 위험</h3>
            <ul>
              {(content.key_risks || []).map((item) => (
                <li key={item}>{displayText(item)}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>자산별 전략</h2>
        {isLoading ? (
          <p className="empty-state">전략을 불러오는 중입니다.</p>
        ) : (
          <>
            <div className="filter-row">
              {strategyFilters.map((filter) => (
                <button
                  className={strategyFilter === filter ? "active" : ""}
                  key={filter}
                  type="button"
                  onClick={() => setStrategyFilter(filter)}
                >
                  {filterLabels[filter]}
                </button>
              ))}
            </div>
            <StrategyTable strategies={filteredStrategies} />
          </>
        )}
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>추가 매수 후보</h2>
            <p>보유 자산이 아닌 기본 후보군을 기술 점수로 선별한 결과입니다.</p>
          </div>
          <div className="inline-metrics">
            <span>{candidateStrategies.length}개 후보</span>
          </div>
        </div>
        <StrategyTable strategies={candidateStrategies} />
      </section>

      <section className="panel">
        <h2>성과 추적</h2>
        {isLoading ? (
          <p className="empty-state">성과 로그를 불러오는 중입니다.</p>
        ) : (
          <PerformanceTable logs={selectedPerformanceLogs} />
        )}
      </section>
    </section>
  );
}

function formatReturn(value) {
  if (value == null) return "-";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return "-";
  return `${numeric.toFixed(2)}%`;
}

function formatValue(value) {
  if (value == null) return "-";
  const numeric = Number(value);
  if (Number.isNaN(numeric)) return value;
  return numeric.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function PerformanceTable({ logs = [] }) {
  if (!logs.length) {
    return <p className="empty-state">이 리포트에 연결된 성과 로그가 아직 없습니다.</p>;
  }
  const summary = performanceSummary(logs);

  return (
    <>
      <div className="metric-grid compact performance-summary">
        <div>
          <span>평가 로그</span>
          <strong>{logs.length}</strong>
        </div>
        <div>
          <span>1일 평균</span>
          <strong>{formatReturn(summary.return_after_1d)}</strong>
        </div>
        <div>
          <span>5일 평균</span>
          <strong>{formatReturn(summary.return_after_5d)}</strong>
        </div>
        <div>
          <span>20일 평균</span>
          <strong>{formatReturn(summary.return_after_20d)}</strong>
        </div>
      </div>
      <div className="performance-card-list">
        {logs.map((row) => (
          <article className="performance-card" key={row.id}>
            <div className="asset-card-header">
              <div>
                <strong>{row.ticker}</strong>
                <span>{row.name || row.action}</span>
              </div>
              <span className={`badge ${row.action.toLowerCase()}`}>
                {actionLabel(row.action)}
              </span>
            </div>
            <dl>
              <div>
                <dt>추천 당시 가격</dt>
                <dd>{formatValue(row.price_at_recommendation)}</dd>
              </div>
              <div>
                <dt>1일</dt>
                <dd>{formatReturn(row.return_after_1d)}</dd>
              </div>
              <div>
                <dt>5일</dt>
                <dd>{formatReturn(row.return_after_5d)}</dd>
              </div>
              <div>
                <dt>20일</dt>
                <dd>{formatReturn(row.return_after_20d)}</dd>
              </div>
            </dl>
          </article>
        ))}
      </div>
      <div className="table-wrap performance-table">
        <table>
          <thead>
            <tr>
              <th>티커</th>
              <th>전략</th>
              <th>추천 당시 가격</th>
              <th>1일 후 가격</th>
              <th>1일 수익률</th>
              <th>5일 후 가격</th>
              <th>5일 수익률</th>
              <th>20일 후 가격</th>
              <th>20일 수익률</th>
              <th>평가 시간</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((row) => (
              <tr key={row.id}>
                <td>
                  <strong>{row.ticker}</strong>
                  <span>{row.name || "-"}</span>
                </td>
                <td>
                  <span className={`badge ${row.action.toLowerCase()}`}>
                    {actionLabel(row.action)}
                  </span>
                </td>
                <td>{formatValue(row.price_at_recommendation)}</td>
                <td>{formatValue(row.price_after_1d)}</td>
                <td>{formatReturn(row.return_after_1d)}</td>
                <td>{formatValue(row.price_after_5d)}</td>
                <td>{formatReturn(row.return_after_5d)}</td>
                <td>{formatValue(row.price_after_20d)}</td>
                <td>{formatReturn(row.return_after_20d)}</td>
                <td>{formatReportTime(row.evaluated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function performanceSummary(logs) {
  return {
    return_after_1d: average(logs.map((row) => row.return_after_1d)),
    return_after_5d: average(logs.map((row) => row.return_after_5d)),
    return_after_20d: average(logs.map((row) => row.return_after_20d)),
  };
}

function average(values) {
  const numericValues = values
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
  if (!numericValues.length) return null;
  return numericValues.reduce((sum, value) => sum + value, 0) / numericValues.length;
}
