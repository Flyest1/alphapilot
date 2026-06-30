import { displayText, formatReportTime, reportTitle, trendLabel } from "../../api/reports.js";
import KeyMessageList from "../KeyMessageList.jsx";

function newsStatusLabel(newsContext) {
  const status = newsContext?.status;
  const count = Number(newsContext?.article_count || 0);
  if (status === "ok") return `뉴스 ${count}건 반영`;
  if (status === "empty") return "뉴스 결과 없음";
  if (status === "unavailable") {
    const reasons = newsContext?.failure_reasons || [];
    if (reasons.includes("rate_limited")) return "뉴스 제한: GDELT 호출량 초과";
    return "뉴스 연결 제한";
  }
  return "뉴스 상태 미기록";
}

function newsStatusClass(newsContext) {
  if (newsContext?.status === "ok") return "ok";
  if (newsContext?.status === "unavailable") return "warning";
  return "";
}

// 선택된 리포트의 본문(핵심 메시지, 시장 요약, 기회/위험)을 렌더링한다.
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
  const newsContext = selected?.report_inputs?.news_context;

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
          <span className={`status-pill ${newsStatusClass(newsContext)}`}>
            {newsStatusLabel(newsContext)}
          </span>
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
      <p>{displayText(content.market_summary?.summary) || "표시할 리포트 내용이 없습니다."}</p>
      {!!content.market_summary?.macro_factors?.length && (
        <>
          <h3>시장·뉴스 동향</h3>
          <ul>
            {content.market_summary.macro_factors.map((item) => (
              <li key={item}>{displayText(item)}</li>
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
  );
}
