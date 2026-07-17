function positionTotal(positions) {
  return positions.reduce((total, position) => total + (Number(position.weight_pct) || 0), 0);
}

export default function AdvisoryInputForm({ feature, form, isSubmitting, onChange, onSubmit }) {
  const isTickerList = feature.inputMode === "tickers";
  const isSingleTicker = feature.inputMode === "ticker";
  const isPositions = feature.inputMode === "positions";

  function updatePosition(index, field, value) {
    onChange({
      ...form,
      positions: form.positions.map((position, positionIndex) =>
        positionIndex === index ? { ...position, [field]: value } : position,
      ),
    });
  }

  function addPosition() {
    onChange({ ...form, positions: [...form.positions, { ticker: "", weight_pct: "" }] });
  }

  function removePosition(index) {
    onChange({
      ...form,
      positions: form.positions.filter((_, positionIndex) => positionIndex !== index),
    });
  }

  return (
    <section className="panel advisory-input-panel">
      <div className="section-heading">
        <div>
          <h2>{feature.title}</h2>
          <p>{feature.description}</p>
        </div>
      </div>
      <form onSubmit={onSubmit}>
        {isTickerList && (
          <label className="advisory-field" htmlFor="advisory-tickers">
            <span>분석할 티커 (선택)</span>
            <input
              id="advisory-tickers"
              placeholder="예: AAPL, MSFT, NVDA"
              value={form.tickers}
              onChange={(event) => onChange({ ...form, tickers: event.target.value })}
            />
            <small>
              비워 두면 기본 유니버스 <code>{feature.defaultUniverse}</code>를 사용합니다.
            </small>
          </label>
        )}
        {isSingleTicker && (
          <label className="advisory-field" htmlFor="advisory-ticker">
            <span>SEC 공시를 확인할 티커</span>
            <input
              id="advisory-ticker"
              placeholder="예: AAPL"
              required
              value={form.ticker}
              onChange={(event) => onChange({ ...form, ticker: event.target.value })}
            />
            <small>미국 상장 종목의 영문 티커를 입력하세요.</small>
          </label>
        )}
        {isPositions && (
          <div className="advisory-positions">
            <div className="advisory-position-heading">
              <strong>ETF 보유 비중 (선택)</strong>
              <span>현재 합계 {positionTotal(form.positions).toFixed(1)}%</span>
            </div>
            {form.positions.map((position, index) => (
              <div className="advisory-position-row" key={`${index}-${position.ticker}`}>
                <label>
                  <span className="sr-only">ETF 티커 {index + 1}</span>
                  <input
                    aria-label={`ETF 티커 ${index + 1}`}
                    placeholder="ETF 티커"
                    value={position.ticker}
                    onChange={(event) => updatePosition(index, "ticker", event.target.value)}
                  />
                </label>
                <label>
                  <span className="sr-only">비중 {index + 1}</span>
                  <input
                    aria-label={`비중 ${index + 1}`}
                    inputMode="decimal"
                    min="0"
                    placeholder="비중 (%)"
                    type="number"
                    value={position.weight_pct}
                    onChange={(event) => updatePosition(index, "weight_pct", event.target.value)}
                  />
                </label>
                <button
                  aria-label={`ETF ${index + 1} 제거`}
                  className="secondary-action compact-action"
                  disabled={form.positions.length === 1}
                  type="button"
                  onClick={() => removePosition(index)}
                >
                  제거
                </button>
              </div>
            ))}
            <button className="secondary-action compact-action" type="button" onClick={addPosition}>
              ETF 추가
            </button>
            <p className="field-hint">
              비중을 비워 두면 동일 비중으로 분석합니다. 리밸런싱은 ETF를 입력하지 않으면 저장된 ETF
              자산을 사용합니다.
            </p>
          </div>
        )}
        {feature.inputMode === "none" && (
          <p className="field-hint">추가 입력 없이 지정된 10개 섹터를 분석합니다.</p>
        )}
        <div className="advisory-submit-row">
          <p className="field-hint">
            결과는 투자 정보이며 자동매매·주문 실행 기능을 제공하지 않습니다.
          </p>
          <button disabled={isSubmitting} type="submit">
            {isSubmitting ? "AI 자문 요청 중…" : "AI 자문 요청"}
          </button>
        </div>
      </form>
    </section>
  );
}
