import AdvisoryResultView, {
  AdvisoryEvidence,
  AdvisoryPriorityNotices,
} from "./AdvisoryResultView.jsx";
import { formatAdvisoryValue, isRecord, labelFor, statusLabel } from "./advisoryResultUtils.js";

const AI_NARRATIVE_ALERTS = {
  not_configured: "OpenAI 자문 설명이 설정되지 않아 결정론적 분석만 표시합니다.",
  failed: "AI 자문 설명 생성에 실패해 결정론적 분석만 표시합니다.",
  generation_failed: "AI 자문 설명 생성에 실패해 결정론적 분석만 표시합니다.",
  no_evidence: "인용 가능한 근거가 없어 AI 자문 설명을 생성하지 않았습니다.",
};

function firstDefined(...values) {
  return values.find((value) => value != null && value !== "");
}

function Meta({ label, value, field }) {
  return (
    <span>
      <strong>{label}</strong>
      {value == null || value === "" ? "제공되지 않음" : formatAdvisoryValue(field, value)}
    </span>
  );
}

function narrativeText(value) {
  if (value == null || value === "") return "-";
  if (Array.isArray(value)) {
    return value
      .slice(0, 10)
      .map((item) => narrativeText(item))
      .join(" · ");
  }
  if (typeof value === "object") return "제공 형식 확인 필요";
  return formatAdvisoryValue("text", value);
}

function NarrativePoints({ title, points }) {
  if (!Array.isArray(points) || !points.length) return null;
  return (
    <section>
      <h4>{title}</h4>
      <ul className="advisory-narrative-points">
        {points.slice(0, 10).map((point, index) => {
          const normalizedPoint = isRecord(point) ? point : { text: point };
          return (
            <li key={`${title}-${index}`}>
              <p>{narrativeText(normalizedPoint.text)}</p>
              {normalizedPoint.point_type && (
                <span className="advisory-status-badge neutral">
                  {formatAdvisoryValue("point_type", normalizedPoint.point_type)}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function AdvisoryNarrative({ narrative }) {
  if (!isRecord(narrative)) return null;
  const limitations = Array.isArray(narrative.limitations)
    ? narrative.limitations.slice(0, 10)
    : narrative.limitations != null
      ? [narrative.limitations]
      : [];

  return (
    <section className="advisory-result-section advisory-narrative">
      <h3>AI 설명</h3>
      {narrative.summary != null && (
        <div className="advisory-narrative-summary">
          <p>{narrativeText(narrative.summary)}</p>
        </div>
      )}
      <div className="advisory-narrative-grid">
        <NarrativePoints title="핵심 발견" points={narrative.key_findings} />
        <NarrativePoints title="핵심 위험" points={narrative.key_risks} />
        <NarrativePoints title="검토할 사항" points={narrative.actions_to_consider} />
        {limitations.length > 0 && (
          <section>
            <h4>AI 설명의 한계</h4>
            <ul className="advisory-list">
              {limitations.map((limitation, index) => (
                <li key={`narrative-limitation-${index}`}>{narrativeText(limitation)}</li>
              ))}
            </ul>
          </section>
        )}
      </div>
      {narrative.disclaimer && <p className="field-hint">{narrativeText(narrative.disclaimer)}</p>}
    </section>
  );
}

export default function AdvisoryResult({ analysis }) {
  const storedResult = analysis?.result || analysis?.content || analysis;
  if (!storedResult || typeof storedResult !== "object" || Array.isArray(storedResult)) return null;
  const result = {
    ...storedResult,
    analysis_type: storedResult.analysis_type || analysis?.analysis_type,
  };
  const dataQuality =
    result.data_quality && typeof result.data_quality === "object" ? result.data_quality : {};
  const aiNarrativeStatus = firstDefined(result.ai_narrative_status, analysis?.ai_narrative_status);
  const aiNarrativeState =
    typeof aiNarrativeStatus === "object"
      ? aiNarrativeStatus.reason || aiNarrativeStatus.status
      : aiNarrativeStatus;
  const providers = firstDefined(dataQuality.providers, dataQuality.provider, result.provider);
  const missingFields = firstDefined(result.missing_fields, dataQuality.missing_fields);
  const limitations = firstDefined(result.limitations, dataQuality.limitations);
  const summary = typeof result.ai_narrative === "string" ? result.ai_narrative : result.summary;
  const structuredNarrative = isRecord(result.ai_narrative) ? result.ai_narrative : null;

  return (
    <section className="panel advisory-result-panel">
      <div className="section-heading">
        <div>
          <h2>자문 결과</h2>
          <p>
            모든 내용은 투자 의사결정 참고 정보이며, 주문 또는 자동매매 기능을 제공하지 않습니다.
          </p>
        </div>
      </div>
      <AdvisoryPriorityNotices result={result} />
      {AI_NARRATIVE_ALERTS[aiNarrativeState] && (
        <p className="notice" role="status">
          <span className="alert">AI 설명 상태: {AI_NARRATIVE_ALERTS[aiNarrativeState]}</span>
        </p>
      )}
      {summary && (
        <section className="advisory-result-section">
          <h3>요약</h3>
          <p>{formatAdvisoryValue("summary", summary)}</p>
        </section>
      )}
      <AdvisoryNarrative narrative={structuredNarrative} />
      <AdvisoryResultView result={result} />
      {result.disclaimer && (
        <section className="advisory-result-section">
          <h3>{labelFor("disclaimer")}</h3>
          <p>{formatAdvisoryValue("disclaimer", result.disclaimer)}</p>
        </section>
      )}
      <details className="advisory-supporting-details">
        <summary>추가 메타데이터 및 근거</summary>
        <div className="advisory-supporting-content">
          <div className="advisory-result-meta">
            <Meta
              label="데이터 기준일"
              field="source_as_of"
              value={firstDefined(result.source_as_of, dataQuality.source_as_of, dataQuality.as_of)}
            />
            <Meta
              label="생성 시각"
              field="generated_at"
              value={firstDefined(
                result.generated_at,
                analysis?.generated_at,
                analysis?.created_at,
              )}
            />
            <Meta
              label="조회 시각"
              field="retrieved_at"
              value={firstDefined(result.retrieved_at, dataQuality.retrieved_at)}
            />
            <Meta
              label="제공처"
              field="provider"
              value={Array.isArray(providers) ? providers.join(", ") : providers}
            />
            <Meta
              label="데이터 상태"
              field="status"
              value={statusLabel(dataQuality.status || result.evaluation_status)}
            />
            <Meta
              label="누락 필드"
              field="missing_fields"
              value={Array.isArray(missingFields) ? missingFields.join(", ") : missingFields}
            />
            <Meta
              label="제한 사항"
              field="limitations"
              value={Array.isArray(limitations) ? limitations.join(" · ") : limitations}
            />
          </div>
          <AdvisoryEvidence evidence={result.evidence} />
        </div>
      </details>
    </section>
  );
}
