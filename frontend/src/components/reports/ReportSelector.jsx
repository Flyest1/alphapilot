import {
  dataLimitedCount,
  formatReportTime,
  reportAiModeLabel,
  reportTitle,
  reportTypeLabel,
  strategyCount,
} from "../../api/reports.js";
import { MESSAGES } from "../../constants/strings.js";

const REPORT_TYPES = ["domestic", "global"];

// 리포트 타입 선택 + 최신 리포트 요약 + 이력 목록.
export default function ReportSelector({
  latest,
  activeType,
  selected,
  isLoading,
  filteredReports,
  visibleReports,
  latestSplit,
  onSelectType,
  onSelectReport,
  onShowMore,
}) {
  const latestForActiveType = latest[activeType];

  return (
    <>
      <div className="segmented-control">
        {REPORT_TYPES.map((type) => (
          <button
            className={activeType === type ? "active" : ""}
            key={type}
            type="button"
            onClick={() => onSelectType(type)}
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
              <p className="empty-state">{MESSAGES.noReports}</p>
            )}
            {visibleReports.map((report) => (
              <button
                className={selected?.id === report.id ? "active" : ""}
                key={report.id}
                type="button"
                onClick={() => onSelectReport(report)}
              >
                <strong>{reportTitle(report)}</strong>
                <span>
                  {formatReportTime(report.created_at)} · {strategyCount(report)}개 전략
                </span>
              </button>
            ))}
            {filteredReports.length > visibleReports.length && (
              <button type="button" onClick={onShowMore}>
                <strong>이전 리포트 더 보기</strong>
                <span>
                  {visibleReports.length} / {filteredReports.length}개 표시 중
                </span>
              </button>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
