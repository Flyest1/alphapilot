import {
  archivesUrl,
  evidenceUrl,
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

function Evidence({ evidence }) {
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
                  <dd>{item.source_as_of || item.as_of || "미상"}</dd>
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
          N-PORT 보유·흐름 정보는 {nport.filingPeriod || "공시 기준일 미상"} 기준의 공시 지연
          자료입니다{nport.delay != null ? ` (${nport.delay}일 지연)` : ""}. 현재 또는 일별 ETF
          흐름으로 해석하지 마세요.
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
    "generated_at",
    "retrieved_at",
    "source_as_of",
    "latest_filings",
    ...config.sections
      .filter((section) => Array.isArray(result[section.key]))
      .map((section) => section.key),
  ]);
  return (
    <>
      <section className="advisory-result-title">
        <h3>{config.title}</h3>
        {result.risk_rating && <StatusBadge value={result.risk_rating} />}
      </section>
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
      {config.sections.map(({ key, ...section }) => (
        <ResultTable key={key} {...section} rows={result[key]} />
      ))}
      <Evidence evidence={result.evidence} />
      <FallbackDetails result={result} knownKeys={knownKeys} />
    </>
  );
}
