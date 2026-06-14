import { buildActionBriefing } from "../../utils/actionBriefing.js";

const TONE_CLASS = {
  positive: "positive-text",
  negative: "negative-text",
  warning: "",
};

// 대시보드 최상단 "오늘 확인할 것" 브리핑 (Phase 6-1)
export default function ActionBriefing({ summary, report, cycles, assets }) {
  const items = buildActionBriefing({ summary, report, cycles, assets });

  return (
    <section className="panel action-briefing">
      <div className="section-heading">
        <div>
          <h2>오늘 확인할 것</h2>
          <p>목표/손절 도달, 드리프트 경고, 신규 후보, 데이터 지연을 한눈에 요약합니다.</p>
        </div>
      </div>
      {items.length === 0 ? (
        <p className="empty-state">오늘 특별히 확인할 항목이 없습니다.</p>
      ) : (
        <ul className="action-briefing-list">
          {items.map((item) => (
            <li className={TONE_CLASS[item.tone] || ""} key={item.key}>
              {item.text}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
