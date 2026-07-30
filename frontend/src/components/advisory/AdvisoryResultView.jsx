import {
  archivesUrl,
  evidenceUrl,
  formatAdvisoryDate,
  formatAdvisoryValue,
  labelFor,
  limitedStatuses,
  nportDisclosure,
  RESULT_CONFIG,
  safeRows,
  sortRows,
  statusLabel,
  visibleFields,
} from "./advisoryResultUtils.js";

const LIMITATION_MESSAGES = {
  partial: "일부 지표가 제한되어 제한사항을 함께 확인하세요.",
  limited: "사용 가능한 데이터 범위가 제한되어 일부 결과만 참고할 수 있습니다.",
  "data-limited": "필수 데이터가 제한되어 결과를 충분한 판단 근거로 사용할 수 없습니다.",
  insufficient_data: "근거가 부족하여 충분한 분석을 제공할 수 없습니다.",
  unavailable: "필수 데이터가 없어 현재 결과를 제공할 수 없습니다.",
};

const PROFIT_TAKING_ACTION_LABELS = {
  SELL: "전량 이익실현 검토",
  REDUCE: "일부 이익실현 검토",
  HOLD: "보유 지속 검토",
  BUY: "추가 노출 검토",
  WATCH: "추가 확인",
};

function StatusBadge({ value }) {
  if (value == null || value === "") return null;
  const normalized = String(value).toLowerCase();
  const tone =
    normalized.includes("risk") ||
    normalized === "caution" ||
    normalized.includes("limited") ||
    normalized.includes("insufficient")
      ? "caution"
      : "neutral";
  return <span className={`advisory-status-badge ${tone}`}>{statusLabel(value)}</span>;
}

function ProfitTakingActionBadge({ value }) {
  if (value == null || value === "") return null;
  return (
    <span className="advisory-status-badge neutral">
      {PROFIT_TAKING_ACTION_LABELS[value] || statusLabel(value)}
    </span>
  );
}

function Value({ field, value }) {
  if (
    field === "action" ||
    field.includes("status") ||
    field === "risk_rating" ||
    field === "classification"
  ) {
    return <StatusBadge value={value} />;
  }
  return <span>{formatAdvisoryValue(field, value)}</span>;
}

function ResultTable({ title, rows: sourceRows, fields, sort }) {
  const rows = sortRows(safeRows(sourceRows), sort);
  if (!rows.length) return null;
  const columns = visibleFields(rows, fields || []);
  if (!columns.length) return null;
  return (
    <section className="advisory-result-section">
      <h3>{title}</h3>
      <div className="table-wrap advisory-table-wrap advisory-desktop-table">
        <table>
          <thead>
            <tr>
              {columns.map((field) => (
                <th key={field}>{labelFor(field)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={row.id || row.ticker || row.name || index}>
                {columns.map((field) => (
                  <td key={field}>
                    <Value field={field} value={row[field]} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="advisory-mobile-cards">
        {rows.map((row, index) => (
          <article key={row.id || row.ticker || row.name || index}>
            <strong>{row.ticker || row.name || `${title} ${index + 1}`}</strong>
            {columns
              .slice(0, 5)
              .filter((field) => field !== "ticker")
              .map((field) => (
                <p key={field}>
                  <span>{labelFor(field)}</span>
                  <Value field={field} value={row[field]} />
                </p>
              ))}
          </article>
        ))}
      </div>
    </section>
  );
}

function SecFilings({ filings }) {
  const rows = safeRows(filings);
  if (!rows.length) return null;
  return (
    <section className="advisory-result-section">
      <h3>최신 SEC 공시</h3>
      <div className="advisory-filing-list">
        {rows.map((filing, index) => {
          const link = archivesUrl(filing);
          return (
            <article key={filing.accession_number || `${filing.form}-${index}`}>
              <div>
                <strong>{filing.form || "SEC 공시"}</strong>
                <StatusBadge value={filing.status || filing.data_quality_status} />
              </div>
              <dl>
                <div>
                  <dt>접수 번호</dt>
                  <dd>{formatAdvisoryValue("accession_number", filing.accession_number)}</dd>
                </div>
                <div>
                  <dt>제출일</dt>
                  <dd>{formatAdvisoryValue("filed_at", filing.filed_at || filing.date)}</dd>
                </div>
              </dl>
              {link ? (
                <a href={link} rel="noreferrer" target="_blank">
                  SEC Archives 원문
                </a>
              ) : (
                <p className="field-hint">공식 SEC Archives 원문 링크를 제공하지 않았습니다.</p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

export function AdvisoryEvidence({ evidence }) {
  const rows = safeRows(evidence);
  if (!rows.length) return null;
  return (
    <section className="advisory-result-section">
      <h3>근거</h3>
      <div className="advisory-evidence-list">
        {rows.map((item, index) => {
          const link = evidenceUrl(item);
          return (
            <article key={item.evidence_id || index}>
              <strong>{item.title || `근거 ${index + 1}`}</strong>
              <dl className="advisory-evidence-meta">
                <div>
                  <dt>근거 ID</dt>
                  <dd>
                    <code>{item.evidence_id || "미제공"}</code>
                  </dd>
                </div>
                <div>
                  <dt>제공처</dt>
                  <dd>{item.provider || "미상"}</dd>
                </div>
                <div>
                  <dt>기준일</dt>
                  <dd>{formatAdvisoryValue("source_as_of", item.source_as_of || item.as_of)}</dd>
                </div>
              </dl>
              {link ? (
                <a href={link} rel="noreferrer" target="_blank">
                  원문 열기
                </a>
              ) : (
                item.url && (
                  <p className="field-hint">
                    제공처와 HTTPS 주소를 검증할 수 없어 링크를 표시하지 않습니다.
                  </p>
                )
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}

const FALLBACK_MAX_FIELDS = 12;
const FALLBACK_MAX_ROWS = 20;
const FALLBACK_MAX_COLUMNS = 8;
const FALLBACK_MAX_DEPTH = 3;

function BoundedKeyValues({ value, depth = 0 }) {
  const entries = Object.entries(value).slice(0, FALLBACK_MAX_FIELDS);
  return (
    <dl className="advisory-key-values advisory-fallback-values">
      {entries.map(([key, item]) => (
        <div key={key}>
          <dt>{labelFor(key)}</dt>
          <dd>
            <BoundedValue field={key} value={item} depth={depth + 1} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function BoundedTable({ rows, depth }) {
  const visibleRows = rows.slice(0, FALLBACK_MAX_ROWS);
  const columns = [...new Set(visibleRows.flatMap((row) => Object.keys(row)))].slice(
    0,
    FALLBACK_MAX_COLUMNS,
  );
  if (!columns.length) return <span>-</span>;
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
          {visibleRows.map((row, index) => (
            <tr key={row.id || row.ticker || row.name || index}>
              {columns.map((column) => (
                <td key={column}>
                  <BoundedValue field={column} value={row[column]} depth={depth + 1} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BoundedValue({ field, value, depth = 0 }) {
  if (value == null) return <span>-</span>;
  if (depth >= FALLBACK_MAX_DEPTH) {
    if (Array.isArray(value)) return <span>{value.length}개 항목</span>;
    if (value && typeof value === "object") {
      const keys = Object.keys(value).slice(0, FALLBACK_MAX_FIELDS);
      return <span>{keys.length ? keys.map(labelFor).join(", ") : "-"}</span>;
    }
    return <Value field={field} value={value} />;
  }
  if (Array.isArray(value)) {
    const visibleValues = value.slice(0, FALLBACK_MAX_ROWS);
    const objectRows = visibleValues.filter(
      (item) => item && typeof item === "object" && !Array.isArray(item),
    );
    if (objectRows.length === visibleValues.length && objectRows.length > 0) {
      return <BoundedTable rows={objectRows} depth={depth} />;
    }
    return (
      <ul className="advisory-list">
        {visibleValues.map((item, index) => (
          <li key={`${field}-${index}`}>
            <BoundedValue field={field} value={item} depth={depth + 1} />
          </li>
        ))}
      </ul>
    );
  }
  if (value && typeof value === "object") {
    return <BoundedKeyValues value={value} depth={depth} />;
  }
  return <Value field={field} value={value} />;
}

function FallbackDetails({ result, knownKeys }) {
  const entries = Object.entries(result).filter(
    ([key, value]) => !knownKeys.has(key) && value != null,
  );
  if (!entries.length) return null;
  return (
    <section className="advisory-result-section">
      <h3>추가 정보</h3>
      <dl className="advisory-key-values">
        {entries.map(([key, value]) => (
          <div key={key}>
            <dt>{labelFor(key)}</dt>
            <dd>
              <BoundedValue field={key} value={value} />
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function textItems(value) {
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") {
          return item.text || item.summary || item.reason || item.detail || "";
        }
        return "";
      })
      .filter(Boolean);
  }
  return value == null || value === "" ? [] : [String(value)];
}

function ReviewKeyValues({ value, fields, showMissing = false }) {
  if (!value || typeof value !== "object") {
    return <p className="field-hint">제공되지 않음</p>;
  }
  const rows = showMissing
    ? fields
    : fields.filter((field) => value[field] != null && value[field] !== "");
  if (!rows.length) return <p className="field-hint">제공되지 않음</p>;
  return (
    <dl className="advisory-key-values">
      {rows.map((field) => (
        <div key={field}>
          <dt>{labelFor(field)}</dt>
          <dd>
            <Value field={field} value={value[field]} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function ProfitTakingReview({ result }) {
  const decision = result.decision && typeof result.decision === "object" ? result.decision : {};
  const position =
    result.position_snapshot && typeof result.position_snapshot === "object"
      ? result.position_snapshot
      : {};
  const reportContext =
    result.report_conflict && typeof result.report_conflict === "object"
      ? result.report_conflict
      : result.latest_report_context && typeof result.latest_report_context === "object"
        ? result.latest_report_context
        : {};
  const reasons = textItems(
    decision.primary_reasons || decision.decision_reason || decision.reasons || result.key_reasons,
  );
  const comparisons = safeRows(result.option_comparison || result.options);
  const triggers = safeRows(result.reassessment_triggers || result.invalidation_conditions);
  const risks = textItems(result.risks);
  const catalysts = textItems(result.catalysts);
  const conclusion = decision.one_line_conclusion || decision.summary || result.summary;

  return (
    <section className="advisory-profit-taking-review" data-testid="profit-taking-review">
      <section className="advisory-profit-decision" aria-label="최종 의견">
        <div>
          <span className="advisory-profit-eyebrow">최종 의견</span>
          <h3>{conclusion || "현재 데이터를 바탕으로 이익실현 여부를 검토합니다."}</h3>
        </div>
        <ProfitTakingActionBadge value={decision.action || result.action || "WATCH"} />
        <ReviewKeyValues
          value={{ ...decision, ...position }}
          fields={[
            "confidence",
            "unrealized_return_pct",
            "position_weight_pct",
            "average_price",
            "current_price",
          ]}
        />
      </section>

      <section className="advisory-result-section" aria-label="핵심 이유">
        <h3>핵심 이유</h3>
        {reasons.length ? (
          <ul className="advisory-list">
            {reasons.map((reason, index) => (
              <li key={`profit-taking-reason-${index}`}>{reason}</li>
            ))}
          </ul>
        ) : (
          <p className="field-hint">핵심 판단 근거를 제공하지 않았습니다.</p>
        )}
      </section>

      <section className="advisory-result-section" aria-label="이익실현 보유 추가노출 비교">
        <h3>이익실현·보유·추가 노출 비교</h3>
        {comparisons.length ? (
          <div className="advisory-profit-option-grid">
            {comparisons.map((option, index) => (
              <article key={option.action || option.name || index}>
                <div>
                  <strong>
                    {option.name ||
                      PROFIT_TAKING_ACTION_LABELS[option.action] ||
                      statusLabel("option")}
                  </strong>
                  <ProfitTakingActionBadge value={option.action} />
                </div>
                {option.current_view && (
                  <p>{formatAdvisoryValue("current_view", option.current_view)}</p>
                )}
                {option.when_it_fits && (
                  <p>{formatAdvisoryValue("when_it_fits", option.when_it_fits)}</p>
                )}
                {option.suitability_score != null && (
                  <span>
                    {formatAdvisoryValue("suitability_score", option.suitability_score)}점
                  </span>
                )}
              </article>
            ))}
          </div>
        ) : (
          <p className="field-hint">비교 시나리오를 제공하지 않았습니다.</p>
        )}
      </section>

      <section className="advisory-result-section" aria-label="기존 리포트와의 비교">
        <h3>기존 리포트와의 비교</h3>
        <p className="field-hint">
          기존 리포트는 비교 정보일 뿐, 이번 이익실현 판단의 점수나 최종 의견에는 영향을 주지
          않습니다.
        </p>
        <ReviewKeyValues
          value={reportContext}
          fields={["action", "confidence", "generated_at", "conflict_status", "conflict_reason"]}
          showMissing
        />
      </section>

      <section className="advisory-result-section" aria-label="재검토 조건">
        <h3>재검토 조건</h3>
        {triggers.length ? (
          <div className="advisory-profit-trigger-list">
            {triggers.map((trigger, index) => (
              <article key={trigger.id || trigger.trigger_type || index}>
                <strong>
                  {formatAdvisoryValue(
                    "trigger_type",
                    trigger.trigger_type || trigger.type || "재검토 조건",
                  )}
                </strong>
                <p>{formatAdvisoryValue("condition", trigger.condition || trigger.summary)}</p>
                {trigger.response && (
                  <small>{formatAdvisoryValue("response", trigger.response)}</small>
                )}
              </article>
            ))}
          </div>
        ) : (
          <p className="field-hint">재검토 조건을 제공하지 않았습니다.</p>
        )}
      </section>

      <details className="advisory-profit-details">
        <summary>세부 점수·가격 기준 보기</summary>
        <section className="advisory-result-section">
          <h3>판단 점수표</h3>
          <ReviewKeyValues
            value={result.scorecard}
            fields={[
              "hold_support_score",
              "realization_pressure_score",
              "add_support_score",
              "technical_score",
            ]}
          />
        </section>
        <section className="advisory-result-section">
          <h3>가격 재검토 기준</h3>
          <ReviewKeyValues
            value={result.price_framework}
            fields={[
              "profit_protection_reference",
              "upside_review_reference",
              "trend_invalidation_reference",
              "review_horizon",
              "note",
            ]}
          />
        </section>
        <section className="advisory-result-section">
          <h3>핵심 위험</h3>
          {risks.length ? (
            <ul className="advisory-list">
              {risks.map((risk, index) => (
                <li key={`profit-taking-risk-${index}`}>{risk}</li>
              ))}
            </ul>
          ) : (
            <p className="field-hint">추가로 확인된 핵심 위험이 없습니다.</p>
          )}
        </section>
        <section className="advisory-result-section">
          <h3>보유·상승 촉매</h3>
          {catalysts.length ? (
            <ul className="advisory-list">
              {catalysts.map((catalyst, index) => (
                <li key={`profit-taking-catalyst-${index}`}>{catalyst}</li>
              ))}
            </ul>
          ) : (
            <p className="field-hint">확인 가능한 보유·상승 촉매가 없습니다.</p>
          )}
        </section>
        {position.profit_basis_note && <p className="field-hint">{position.profit_basis_note}</p>}
      </details>
    </section>
  );
}

export function AdvisoryPriorityNotices({ result }) {
  const limitations = limitedStatuses(result);
  const nport = nportDisclosure(result);
  return (
    <>
      {limitations.map((status) => (
        <p className="notice" key={status} role="alert">
          <span className="alert">데이터 제한 안내: {LIMITATION_MESSAGES[status]}</span>
        </p>
      ))}
      {nport && (
        <p className="notice advisory-nport-notice" role="note">
          N-PORT 보유·흐름 정보는 {formatAdvisoryDate(nport.filingPeriod || "공시 기준일 미상")}{" "}
          기준의 공시 지연 자료입니다{nport.delay != null ? ` (${nport.delay}일 지연)` : ""}. 현재
          또는 일별 ETF 흐름으로 해석하지 마세요.
        </p>
      )}
    </>
  );
}

export default function AdvisoryResultView({ result }) {
  const config = RESULT_CONFIG[result.analysis_type] || { title: "AI 자문 결과", sections: [] };
  const knownKeys = new Set([
    "analysis_type",
    "data_quality",
    "evidence",
    "disclaimer",
    "ai_narrative",
    "ai_narrative_status",
    "summary",
    "beginner_explanation",
    "rating_reason",
    "risk_rating",
    "missing_fields",
    "limitations",
    "provider",
    "generated_at",
    "retrieved_at",
    "source_as_of",
    "latest_filings",
    "position_snapshot",
    "decision",
    "option_comparison",
    "options",
    "key_reasons",
    "report_conflict",
    "latest_report_context",
    "reassessment_triggers",
    "invalidation_conditions",
    "scorecard",
    "price_framework",
    "risks",
    "catalysts",
    "evaluation_status",
    ...config.sections
      .filter((section) => Array.isArray(result[section.key]))
      .map((section) => section.key),
  ]);
  return (
    <>
      {result.analysis_type === "profit_taking_review" && <ProfitTakingReview result={result} />}
      {result.analysis_type !== "profit_taking_review" && (
        <section className="advisory-result-title">
          <h3>{config.title}</h3>
          {result.risk_rating && <StatusBadge value={result.risk_rating} />}
        </section>
      )}
      {result.beginner_explanation && (
        <section className="advisory-result-section">
          <h3>초보자 안내</h3>
          <p>{formatAdvisoryValue("beginner_explanation", result.beginner_explanation)}</p>
        </section>
      )}
      {result.rating_reason && (
        <section className="advisory-result-section">
          <h3>위험 등급 근거</h3>
          <p>{formatAdvisoryValue("rating_reason", result.rating_reason)}</p>
        </section>
      )}
      {result.analysis_type === "sec_filing_risk" && <SecFilings filings={result.latest_filings} />}
      {result.analysis_type !== "profit_taking_review" &&
        config.sections.map(({ key, ...section }) => (
          <ResultTable key={key} {...section} rows={result[key]} />
        ))}
      <FallbackDetails result={result} knownKeys={knownKeys} />
    </>
  );
}
