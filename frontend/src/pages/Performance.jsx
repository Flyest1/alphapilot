import { useEffect, useState } from "react";

import { api, isApiCacheFresh, readApiCache } from "../api/client.js";
import SignalModelEvaluationPanel from "../components/SignalModelEvaluationPanel.jsx";
import Skeleton from "../components/Skeleton.jsx";
import SummaryCard from "../components/SummaryCard.jsx";
import { MESSAGES } from "../constants/strings.js";
import {
  backtestSummary,
  baselineRows,
  costRows,
  marketRows,
  metricValue,
  regimeRows,
  signalResearchRows,
  walkForwardRows,
} from "../utils/backtestResults.js";
import { formatReturn } from "../utils/formatters.js";
import { groupTitle, statsHeadlines } from "../utils/recommendationStats.js";

const STATS_CACHE_MS = 5 * 60 * 1000;
const STATS_PATH = "/api/recommendation-stats";
const EVALUATION_PATH = "/api/signal-models/evaluation";

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
  const [backtest, setBacktest] = useState(null);
  const [backtestLoading, setBacktestLoading] = useState(false);
  const cachedEvaluation = readApiCache(EVALUATION_PATH, { maxAgeMs: STATS_CACHE_MS });
  const [evaluation, setEvaluation] = useState(cachedEvaluation);
  const [evaluationLoading, setEvaluationLoading] = useState(!cachedEvaluation);
  const [evaluationError, setEvaluationError] = useState(null);

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

  function loadEvaluation() {
    setEvaluationLoading(true);
    api.signalModels
      .evaluation()
      .then((result) => {
        setEvaluation(result);
        setEvaluationError(null);
      })
      .catch((err) => {
        setEvaluation(null);
        setEvaluationError(err);
      })
      .finally(() => setEvaluationLoading(false));
  }

  useEffect(() => {
    if (!isApiCacheFresh(STATS_PATH, STATS_CACHE_MS)) {
      loadStats();
    }
    if (!isApiCacheFresh(EVALUATION_PATH, STATS_CACHE_MS)) {
      loadEvaluation();
    }
  }, []);

  async function runBacktest(reportType) {
    setBacktestLoading(true);
    setError("");
    try {
      setBacktest(await api.backtests.runRules(reportType));
    } catch (err) {
      setError(err.message);
    } finally {
      setBacktestLoading(false);
    }
  }

  const totals = stats?.totals || {};
  const groups = stats?.groups || [];
  const headlines = statsHeadlines(stats);
  const minSample = stats?.min_sample_for_calibration ?? 30;
  const backtestCards = backtestSummary(backtest);
  const backtestBaselines = baselineRows(backtest);
  const backtestCosts = costRows(backtest);
  const backtestRegimes = regimeRows(backtest);
  const backtestFolds = walkForwardRows(backtest);
  const backtestMarkets = marketRows(backtest);
  const researchSignals = signalResearchRows(backtest);
  const showSignalResearch =
    backtest?.signal_research?.research_only === true &&
    backtest?.signal_research?.adoption_permitted === false;

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

      <SignalModelEvaluationPanel
        error={evaluationError}
        evaluation={evaluation}
        isLoading={evaluationLoading}
      />

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>점수 규칙 백테스트</h2>
            <p>후보 유니버스 과거 가격으로 점수→액션 규칙을 별도 시뮬레이션합니다.</p>
          </div>
          <div className="header-actions">
            <button
              disabled={backtestLoading}
              type="button"
              onClick={() => runBacktest("domestic")}
            >
              국내 규칙 검증
            </button>
            <button disabled={backtestLoading} type="button" onClick={() => runBacktest("global")}>
              글로벌 규칙 검증
            </button>
          </div>
        </div>
        {backtestLoading && <Skeleton label="과거 가격 규칙을 검증하는 중입니다." lines={3} />}
        {!backtestLoading && !backtest && (
          <p className="empty-state">
            버튼을 눌러 리포트 생성과 분리된 규칙 시뮬레이션을 실행하세요.
          </p>
        )}
        {backtest && (
          <>
            <div className="inline-metrics">
              <span>{backtest.tickers_tested.length}개 종목</span>
              <span>{backtest.sample_count}개 표본</span>
              <span>{backtest.forward_days}거래일 후 수익률</span>
              {backtest.strategy_version && <span>모델 {backtest.strategy_version}</span>}
            </div>
            {backtest.metrics && (
              <div className="metric-grid compact performance-summary">
                {backtestCards.map((row) => (
                  <div key={row.label}>
                    <span>{row.label}</span>
                    <strong>{row.value}</strong>
                  </div>
                ))}
              </div>
            )}
            <div className="table-wrap">
              <table className="compact-table">
                <thead>
                  <tr>
                    <th>규칙 액션</th>
                    <th>표본</th>
                    <th>평균 향후 수익률</th>
                    <th>비용 차감 평균</th>
                    <th>방향 적중률</th>
                  </tr>
                </thead>
                <tbody>
                  {backtest.groups.map((group) => (
                    <tr key={group.action}>
                      <td>{group.action}</td>
                      <td>{group.sample_count}</td>
                      <td>{formatReturn(group.avg_forward_return)}</td>
                      <td>{formatReturn(group.avg_net_return_pct)}</td>
                      <td>{formatWinRate(group.directional_success_rate)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {backtestBaselines.length > 0 && (
              <div className="table-wrap">
                <table className="compact-table">
                  <thead>
                    <tr>
                      <th>기준선</th>
                      <th>비용 전 누적</th>
                      <th>비용 후 누적</th>
                      <th>단순 보유</th>
                      <th>초과 성과</th>
                      <th>최대 낙폭</th>
                    </tr>
                  </thead>
                  <tbody>
                    {backtestBaselines.map((row) => (
                      <tr key={row.name}>
                        <td>{row.name}</td>
                        <td>{metricValue(row.gross, 2, "%")}</td>
                        <td>{metricValue(row.net, 2, "%")}</td>
                        <td>{metricValue(row.drawdown, 2, "%")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {backtestRegimes.length > 0 && (
              <div className="table-wrap">
                <table className="compact-table">
                  <thead>
                    <tr>
                      <th>시장 국면</th>
                      <th>표본</th>
                      <th>비용 차감 평균</th>
                    </tr>
                  </thead>
                  <tbody>
                    {backtestRegimes.map((row) => (
                      <tr key={row.regime}>
                        <td>{row.label}</td>
                        <td>{row.sample_count}</td>
                        <td>{metricValue(row.avg_net_return_pct, 2, "%")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {backtestMarkets.length > 0 && (
              <div className="table-wrap">
                <table className="compact-table">
                  <thead>
                    <tr>
                      <th>시장</th>
                      <th>표본</th>
                      <th>비용 후 누적</th>
                      <th>최대 낙폭</th>
                      <th>Sharpe</th>
                      <th>외부 평가 fold</th>
                    </tr>
                  </thead>
                  <tbody>
                    {backtestMarkets.map((row) => (
                      <tr key={row.market}>
                        <td>{row.market}</td>
                        <td>{row.sampleCount}</td>
                        <td>{metricValue(row.netReturn, 2, "%")}</td>
                        <td>{metricValue(row.benchmarkReturn, 2, "%")}</td>
                        <td>{metricValue(row.excessReturn, 2, "%p")}</td>
                        <td>{metricValue(row.drawdown, 2, "%")}</td>
                        <td>{metricValue(row.sharpe)}</td>
                        <td>{row.foldCount}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {backtestFolds.length > 0 && (
              <div className="table-wrap">
                <table className="compact-table">
                  <thead>
                    <tr>
                      <th>워크포워드</th>
                      <th>학습/평가 표본</th>
                      <th>평가 기간</th>
                      <th>비용 후 누적</th>
                      <th>최대 낙폭</th>
                    </tr>
                  </thead>
                  <tbody>
                    {backtestFolds.map((row) => (
                      <tr key={row.fold}>
                        <td>Fold {row.fold}</td>
                        <td>
                          {row.trainCount}/{row.testCount}
                        </td>
                        <td>{row.period}</td>
                        <td>{metricValue(row.netReturn, 2, "%")}</td>
                        <td>{metricValue(row.drawdown, 2, "%")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {showSignalResearch && (
              <section className="panel nested-panel">
                <div className="section-heading">
                  <div>
                    <h3>직교 신호 연구 진단</h3>
                    <p>연구 전용 결과이며 운영 점수와 추천 액션에는 반영되지 않습니다.</p>
                  </div>
                  <span className="status-pill warning">운영 미반영</span>
                </div>
                {researchSignals.length === 0 ? (
                  <p className="empty-state">평가 가능한 연구 신호가 없습니다.</p>
                ) : (
                  <div className="table-wrap">
                    <table className="compact-table">
                      <thead>
                        <tr>
                          <th>신호</th>
                          <th>상태</th>
                          <th>표본</th>
                          <th>상·하위 순수익 차이</th>
                          <th>증분 기대값</th>
                          <th>기술점수 상관</th>
                          <th>유효 fold</th>
                          <th>제외 사유</th>
                        </tr>
                      </thead>
                      <tbody>
                        {researchSignals.map((row) => (
                          <tr key={row.signal}>
                            <td>{row.signal}</td>
                            <td>{row.statusLabel}</td>
                            <td>{row.sampleCount}</td>
                            <td>{metricValue(row.spread, 2, "%p")}</td>
                            <td>{metricValue(row.incrementalValue, 2, "%p")}</td>
                            <td>{metricValue(row.technicalCorrelation)}</td>
                            <td>{row.validFoldCount}</td>
                            <td>{row.reasons.join(", ") || "-"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <p className="field-hint">{backtest.signal_research.disclaimer}</p>
              </section>
            )}
            {backtest.costs && (
              <div className="inline-metrics">
                {backtestCosts.map((row) => (
                  <span key={row.label}>
                    {row.label} {metricValue(row.value, 3, "%")}
                  </span>
                ))}
              </div>
            )}
            {backtest.walk_forward?.stability_warning && (
              <p className="alert">{backtest.walk_forward.stability_warning}</p>
            )}
            {(backtest.bias_warnings || []).length > 0 && (
              <ul className="field-hint">
                {backtest.bias_warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            )}
            <p className="field-hint">{backtest.disclaimer}</p>
          </>
        )}
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
