import { formatValue } from "../../utils/formatters.js";

const LABELS = {
  as_of: "데이터 기준시각",
  generated_at: "생성 시각",
  updated_at: "갱신 시각",
  retrieved_at: "조회 시각",
  source_as_of: "원천 데이터 기준일",
  missing_fields: "누락 필드",
  limitations: "한계",
  data_quality: "데이터 품질",
  summary: "요약",
  tables: "분석 표",
  rankings: "순위",
  scenarios: "시나리오",
  evidence: "근거",
  disclaimer: "안내",
  details: "핵심 판단",
  provider: "제공자",
  providers: "제공자",
  status: "상태",
  freshness: "신선도",
  analysis_status: "분석 상태",
  evidence_id: "근거 ID",
  url: "원문",
  risk_rating: "위험 등급",
};

const VALUE_LABELS = {
  available: "사용 가능",
  fresh: "최신",
  partial: "일부 제한",
  limited: "제한됨",
  "data-limited": "데이터 제한",
  insufficient_data: "근거 부족",
  unavailable: "평가 불가",
  relative_low_risk: "상대적 위험 낮음",
  caution: "주의",
  high_risk: "고위험",
  BUY: "매수 검토 후보",
  WATCH: "관찰",
  HOLD: "보유 검토",
  REDUCE: "비중 축소 검토",
  SELL: "매도 검토",
};

const DATA_QUALITY_ALERTS = {
  partial: "일부 데이터가 제한되어 결과를 전체 판단으로 사용할 수 없습니다.",
  limited: "데이터가 제한되어 일부 결과만 참고용으로 확인해야 합니다.",
  "data-limited": "필수 데이터가 제한되어 수치와 판단을 그대로 신뢰할 수 없습니다.",
  unavailable: "필수 데이터가 없어 이 결과는 평가 불가 상태입니다.",
  insufficient_data: "근거가 부족해 충분한 분석을 수행할 수 없습니다.",
};

const AI_NARRATIVE_ALERTS = {
  not_configured: "OpenAI 자문 설명이 설정되지 않아 결정론적 분석만 표시합니다.",
  failed: "AI 설명 생성에 실패해 결정론적 분석만 표시합니다.",
  generation_failed: "AI 설명 생성에 실패해 결정론적 분석만 표시합니다.",
  no_evidence: "인용 가능한 근거가 없어 AI 설명을 생성하지 않았습니다.",
};

function labelFor(key) {
  return LABELS[key] || String(key).replace(/_/g, " ");
}

function displayValue(value) {
  if (value == null) return "-";
  if (typeof value === "boolean") return value ? "예" : "아니오";
  if (typeof value === "number") return formatValue(value);
  return VALUE_LABELS[value] || String(value);
}

function NestedValue({ value }) {
  if (Array.isArray(value)) {
    if (!value.length) return <span>-</span>;
    if (value.some((item) => item && typeof item === "object")) {
      return (
        <ul className="advisory-list">
          {value.map((item, index) => (
            <li key={item?.evidence_id || item?.ticker || index}>
              <KeyValues value={item} />
            </li>
          ))}
        </ul>
      );
    }
    return <span>{value.map(displayValue).join(", ")}</span>;
  }
  if (value && typeof value === "object") return <KeyValues value={value} />;
  return <span>{displayValue(value)}</span>;
}

function KeyValues({ value }) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return <p>{displayValue(value)}</p>;
  }
  return (
    <dl className="advisory-key-values">
      {Object.entries(value).map(([key, item]) => (
        <div key={key}>
          <dt>{labelFor(key)}</dt>
          <dd>
            <NestedValue value={item} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function GenericTable({ value }) {
  const rows = Array.isArray(value) ? value : value?.rows || value?.items || [];
  if (!Array.isArray(rows) || !rows.length) return <KeyValues value={value} />;
  if (!rows.some((row) => row && typeof row === "object" && !Array.isArray(row))) {
    return (
      <ul className="advisory-list">
        {rows.map((row, index) => (
          <li key={`${row}-${index}`}>
            <NestedValue value={row} />
          </li>
        ))}
      </ul>
    );
  }
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row || {})))];
  return (
    <div className="table-wrap advisory-table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{labelFor(column)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.id || row.ticker || index}>
              {columns.map((column) => (
                <td key={column}>
                  <NestedValue value={row[column]} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EvidenceList({ value }) {
  if (!Array.isArray(value) || !value.length) return <KeyValues value={value} />;
  return (
    <div className="advisory-evidence-list">
      {value.map((item, index) =>
        item && typeof item === "object" ? (
          <article key={item.evidence_id || index}>
            <strong>{item.title || item.evidence_id || `근거 ${index + 1}`}</strong>
            <KeyValues
              value={Object.fromEntries(
                Object.entries(item).filter(([key]) => !["title", "url"].includes(key)),
              )}
            />
            {item.url && (
              <a href={item.url} rel="noreferrer" target="_blank">
                원문 열기
              </a>
            )}
          </article>
        ) : (
          <p key={`${item}-${index}`}>{displayValue(item)}</p>
        ),
      )}
    </div>
  );
}

function ResultSection({ name, value }) {
  if (
    value == null ||
    (Array.isArray(value) && !value.length) ||
    (!Array.isArray(value) && typeof value === "object" && !Object.keys(value).length)
  ) {
    return null;
  }
  const isTable = ["tables", "rankings", "scenarios", "evidence"].includes(name);
  const hasNamedGroups =
    !Array.isArray(value) && typeof value === "object" && !value.rows && !value.items;
  return (
    <section className="advisory-result-section">
      <h3>{labelFor(name)}</h3>
      {isTable && hasNamedGroups ? (
        Object.entries(value).map(([key, item]) => (
          <div className="advisory-result-subsection" key={key}>
            <h4>{labelFor(key)}</h4>
            <GenericTable value={item} />
          </div>
        ))
      ) : isTable ? (
        name === "evidence" ? (
          <EvidenceList value={value} />
        ) : (
          <GenericTable value={value} />
        )
      ) : (
        <KeyValues value={value} />
      )}
    </section>
  );
}

function firstDefined(...values) {
  return values.find((value) => value != null && value !== "");
}

function fallbackTables(result) {
  const excludedKeys = new Set([
    "analysis_type",
    "as_of",
    "generated_at",
    "updated_at",
    "summary",
    "ai_narrative",
    "tables",
    "rankings",
    "top_candidates",
    "scenarios",
    "investor_portfolios",
    "evidence",
    "data_quality",
    "missing_fields",
    "limitations",
    "disclaimer",
    "methodology",
  ]);
  return Object.fromEntries(
    Object.entries(result).filter(
      ([key, value]) =>
        !excludedKeys.has(key) &&
        value != null &&
        (Array.isArray(value) || typeof value === "object"),
    ),
  );
}

function fallbackDetails(result) {
  const excludedKeys = new Set([
    "analysis_type",
    "as_of",
    "generated_at",
    "retrieved_at",
    "updated_at",
    "summary",
    "ai_narrative",
    "data_quality",
    "missing_fields",
    "limitations",
    "disclaimer",
  ]);
  return Object.fromEntries(
    Object.entries(result).filter(
      ([key, value]) =>
        !excludedKeys.has(key) &&
        value != null &&
        !Array.isArray(value) &&
        typeof value !== "object",
    ),
  );
}

export default function AdvisoryResult({ analysis }) {
  const result = analysis?.result || analysis?.content || analysis;
  if (!result || typeof result !== "object") return null;
  const dataQuality = result.data_quality || analysis?.data_quality;
  const asOf = firstDefined(
    result.as_of,
    analysis?.as_of,
    dataQuality?.source_as_of,
    dataQuality?.as_of,
    dataQuality?.as_of_at,
  );
  const generatedAt = firstDefined(
    result.generated_at,
    analysis?.generated_at,
    analysis?.created_at,
  );
  const retrievedAt = firstDefined(result.retrieved_at, dataQuality?.retrieved_at);
  const providers = firstDefined(dataQuality?.providers, dataQuality?.provider, result.provider);
  const freshness = firstDefined(dataQuality?.freshness, dataQuality?.status);
  const aiNarrativeStatus = firstDefined(result.ai_narrative_status, analysis?.ai_narrative_status);
  const aiNarrativeState =
    aiNarrativeStatus && typeof aiNarrativeStatus === "object"
      ? aiNarrativeStatus.reason || aiNarrativeStatus.status
      : aiNarrativeStatus;
  const dataQualityAlert = DATA_QUALITY_ALERTS[dataQuality?.status];
  const aiNarrativeAlert = AI_NARRATIVE_ALERTS[aiNarrativeState];
  const missingFields = firstDefined(
    result.missing_fields,
    analysis?.missing_fields,
    dataQuality?.missing_fields,
  );
  const limitations = firstDefined(
    result.limitations,
    analysis?.limitations,
    dataQuality?.limitations,
  );
  const summary = firstDefined(result.summary, result.ai_narrative);
  const details = fallbackDetails(result);
  const tables = result.tables || fallbackTables(result);
  const rankings = firstDefined(result.rankings, result.top_candidates);
  const scenarios = firstDefined(result.scenarios, result.investor_portfolios);

  return (
    <section className="panel advisory-result-panel">
      <div className="section-heading">
        <div>
          <h2>자문 결과</h2>
          <p>데이터 기준시각과 한계를 확인한 뒤 의사결정 자료로만 활용하세요.</p>
        </div>
      </div>
      {(dataQualityAlert || aiNarrativeAlert) && (
        <div className="advisory-result-notices" aria-live="polite">
          {dataQualityAlert && (
            <p className="notice" role="alert">
              <span className="alert">데이터 제한 안내: {dataQualityAlert}</span>
            </p>
          )}
          {aiNarrativeAlert && (
            <p className="notice" role="status">
              <span className="alert">AI 설명 상태: {aiNarrativeAlert}</span>
            </p>
          )}
        </div>
      )}
      <div className="advisory-result-meta">
        <span>
          <strong>데이터 기준시각</strong>
          {asOf || "제공되지 않음"}
        </span>
        <span>
          <strong>생성 시각</strong>
          {generatedAt || "제공되지 않음"}
        </span>
        <span>
          <strong>조회 시각</strong>
          {retrievedAt || "제공되지 않음"}
        </span>
        <span>
          <strong>제공자</strong>
          {Array.isArray(providers)
            ? providers.join(", ") || "제공되지 않음"
            : providers || "제공되지 않음"}
        </span>
        <span>
          <strong>데이터 상태</strong>
          {freshness ? displayValue(freshness) : "제공되지 않음"}
        </span>
        <span>
          <strong>누락 필드</strong>
          {Array.isArray(missingFields)
            ? missingFields.join(", ") || "없음"
            : missingFields || "제공되지 않음"}
        </span>
        <span>
          <strong>한계</strong>
          {Array.isArray(limitations)
            ? limitations.join(" · ") || "제공되지 않음"
            : limitations || "제공되지 않음"}
        </span>
      </div>
      <ResultSection name="summary" value={summary} />
      <ResultSection name="details" value={details} />
      <ResultSection name="tables" value={tables} />
      <ResultSection name="rankings" value={rankings} />
      <ResultSection name="scenarios" value={scenarios} />
      <ResultSection name="evidence" value={result.evidence} />
      <ResultSection name="data_quality" value={dataQuality} />
      <ResultSection name="disclaimer" value={result.disclaimer} />
    </section>
  );
}
