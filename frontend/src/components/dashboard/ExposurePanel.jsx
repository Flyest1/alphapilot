import { formatMoney } from "../../utils/formatters.js";

function ExposureBars({ title, rows = [] }) {
  if (!rows.length) return null;
  return (
    <div>
      <h3>{title}</h3>
      <div className="bars">
        {rows.map((row) => (
          <div className="bar-row" key={row.key}>
            <div>
              <strong>{row.label}</strong>
              <span>{formatMoney(row.value)} KRW</span>
            </div>
            <div className="bar-track">
              <span style={{ width: `${Math.min(row.weight, 100)}%` }} />
            </div>
            <em>{row.weight}%</em>
          </div>
        ))}
      </div>
    </div>
  );
}

// 통화/시장/섹터 노출 비중과 집중도 경고 (Phase 4-3)
export default function ExposurePanel({ summary }) {
  const warnings = summary?.concentration_warnings || [];
  const hasData =
    (summary?.currency_exposure || []).length ||
    (summary?.market_exposure || []).length ||
    (summary?.sector_exposure || []).length;

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h2>노출 분석</h2>
          <p>통화·시장·섹터별 비중과 집중도 경고입니다. 섹터는 리포트 생성 시 자동 보충됩니다.</p>
        </div>
      </div>
      {warnings.map((warning) => (
        <p className="alert" key={warning}>
          {warning}
        </p>
      ))}
      {!hasData ? (
        <p className="empty-state">표시할 노출 데이터가 아직 없습니다.</p>
      ) : (
        <div className="portfolio-chart-grid">
          <ExposureBars rows={summary?.currency_exposure} title="통화별" />
          <ExposureBars rows={summary?.market_exposure} title="시장별" />
          <ExposureBars rows={summary?.sector_exposure} title="섹터별" />
        </div>
      )}
    </section>
  );
}
