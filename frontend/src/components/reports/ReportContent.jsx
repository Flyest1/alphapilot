import { displayReportText, formatReportTime, reportTitle, trendLabel } from "../../api/reports.js";
import KeyMessageList from "../KeyMessageList.jsx";

export default function ReportContent({
  selected,
  ownedCount,
  candidateCount,
  dataLimitedCountValue,
  technicalOnly,
  performanceLogs,
  performanceDataLoaded = false,
}) {
  const content = selected?.content || {};
  const strategies = content.asset_strategies || [];

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h2>{reportTitle(selected)}</h2>
          <p>{formatReportTime(selected?.created_at)}</p>
        </div>
        <div className="inline-metrics">
          <span>{ownedCount}개 보유 전략</span>
          <span>{candidateCount}개 추가 후보</span>
          <span>{dataLimitedCountValue}개 데이터 제한</span>
          {technicalOnly && <span>기술 지표만</span>}
        </div>
      </div>
      <div className="key-message-panel">
        <div className="subsection-heading">
          <h3>핵심 매매 메시지</h3>
          {!performanceDataLoaded && <span>성과 수익률은 성과 데이터 연결 후 표시</span>}
        </div>
        <KeyMessageList
          performanceLogs={performanceDataLoaded ? performanceLogs : []}
          strategies={strategies}
        />
      </div>
      <p>
        {displayReportText(content.market_summary?.summary) || "표시할 리포트 내용이 없습니다."}
      </p>
      {!!content.market_summary?.macro_factors?.length && (
        <>
          <h3>시장 주요 동향</h3>
          <ul>
            {content.market_summary.macro_factors.map((item) => (
              <li key={item}>{displayReportText(item)}</li>
            ))}
          </ul>
        </>
      )}
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
              <li key={item}>{displayReportText(item)}</li>
            ))}
          </ul>
        </div>
        <div>
          <h3>주요 위험</h3>
          <ul>
            {(content.key_risks || []).map((item) => (
              <li key={item}>{displayReportText(item)}</li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
