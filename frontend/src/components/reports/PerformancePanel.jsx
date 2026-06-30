import { actionLabel, formatReportTime } from "../../api/reports.js";
import { cycleStatusLabel, horizonLabel } from "../../constants/strings.js";
import { average, formatReturn, formatValue } from "../../utils/formatters.js";
import Skeleton from "../Skeleton.jsx";

function RecommendationCycleTable({ cycles = [] }) {
  if (!cycles.length) {
    return <p className="empty-state">이 리포트 종목에 연결된 추천 cycle이 아직 없습니다.</p>;
  }
  const activeCount = cycles.filter((row) => row.status === "active").length;
  return (
    <>
      <div className="metric-grid compact performance-summary">
        <div>
          <span>전체 cycle</span>
          <strong>{cycles.length}</strong>
        </div>
        <div>
          <span>진행 중</span>
          <strong>{activeCount}</strong>
        </div>
        <div>
          <span>목표 도달</span>
          <strong>{cycles.filter((row) => row.status === "hit_target").length}</strong>
        </div>
        <div>
          <span>손절 도달</span>
          <strong>{cycles.filter((row) => row.status === "hit_stop").length}</strong>
        </div>
      </div>
      <div className="performance-card-list">
        {cycles.map((row) => (
          <article className="performance-card" key={row.id}>
            <div className="asset-card-header">
              <div>
                <strong>{row.ticker}</strong>
                <span>
                  {horizonLabel(row.horizon)} · {cycleStatusLabel(row.status)}
                </span>
              </div>
              <span className={`badge ${String(row.action || "watch").toLowerCase()}`}>
                {actionLabel(row.action)}
              </span>
            </div>
            <dl>
              <div>
                <dt>기준 가격</dt>
                <dd>{formatValue(row.reference_price)}</dd>
              </div>
              <div>
                <dt>목표가</dt>
                <dd>{formatValue(row.target_price)}</dd>
              </div>
              <div>
                <dt>손절가</dt>
                <dd>{formatValue(row.stop_loss)}</dd>
              </div>
              <div>
                <dt>60일</dt>
                <dd>{formatReturn(row.return_after_60d)}</dd>
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
              <th>기간</th>
              <th>상태</th>
              <th>기준 가격</th>
              <th>목표가</th>
              <th>손절가</th>
              <th>1일</th>
              <th>5일</th>
              <th>20일</th>
              <th>60일</th>
            </tr>
          </thead>
          <tbody>
            {cycles.map((row) => (
              <tr key={row.id}>
                <td>
                  <strong>{row.ticker}</strong>
                  <span>{row.name || "-"}</span>
                </td>
                <td>
                  <span className={`badge ${String(row.action || "watch").toLowerCase()}`}>
                    {actionLabel(row.action)}
                  </span>
                </td>
                <td>{horizonLabel(row.horizon)}</td>
                <td>{cycleStatusLabel(row.status)}</td>
                <td>{formatValue(row.reference_price)}</td>
                <td>{formatValue(row.target_price)}</td>
                <td>{formatValue(row.stop_loss)}</td>
                <td>{formatReturn(row.return_after_1d)}</td>
                <td>{formatReturn(row.return_after_5d)}</td>
                <td>{formatReturn(row.return_after_20d)}</td>
                <td>{formatReturn(row.return_after_60d)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function PerformanceTable({ logs = [] }) {
  if (!logs.length) {
    return <p className="empty-state">이 리포트에 연결된 성과 로그가 아직 없습니다.</p>;
  }
  const summary = {
    return_after_1d: average(logs.map((row) => row.return_after_1d)),
    return_after_5d: average(logs.map((row) => row.return_after_5d)),
    return_after_20d: average(logs.map((row) => row.return_after_20d)),
  };

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
              <span className={`badge ${row.action.toLowerCase()}`}>{actionLabel(row.action)}</span>
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

// 추천 생애주기 + 성과 로그 패널. 무거운 데이터라 사용자가 요청할 때만 연결한다.
export default function PerformancePanel({
  cycles = [],
  error = "",
  isLoaded = false,
  isLoading = false,
  logs = [],
  selectedTickerCount = 0,
  onLoad,
}) {
  if (!isLoaded) {
    return (
      <section className="panel lazy-data-panel">
        <div className="section-heading">
          <div>
            <h2>성과 추적 데이터</h2>
            <p>추천 생애주기와 기존 성과 로그는 데이터가 커질 수 있어 필요할 때만 연결합니다.</p>
          </div>
          <div className="inline-metrics">
            <span>{selectedTickerCount}개 선택 종목</span>
            <span>지연 로딩</span>
          </div>
        </div>
        {error && <p className="alert">{error}</p>}
        {isLoading ? (
          <Skeleton label="성과 데이터를 연결하는 중입니다." />
        ) : (
          <button className="secondary-action" type="button" onClick={onLoad}>
            추천 생애주기와 성과 로그 보기
          </button>
        )}
      </section>
    );
  }

  return (
    <>
      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>추천 생애주기</h2>
            <p>선택한 리포트 종목과 연결된 추천 추적 상태입니다.</p>
          </div>
          <div className="inline-metrics">
            <span>{cycles.length}개 연결</span>
          </div>
        </div>
        {isLoading ? (
          <Skeleton label="추천 cycle을 불러오는 중입니다." />
        ) : (
          <RecommendationCycleTable cycles={cycles} />
        )}
      </section>

      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>기존 성과 로그</h2>
            <p>선택한 리포트 종목의 과거 추천 성과 로그입니다.</p>
          </div>
          <div className="inline-metrics">
            <span>{logs.length}개 연결</span>
          </div>
        </div>
        {isLoading ? (
          <Skeleton label="성과 로그를 불러오는 중입니다." />
        ) : (
          <PerformanceTable logs={logs} />
        )}
      </section>
    </>
  );
}
