function positionTotal(positions) {
  return positions.reduce((total, position) => total + (Number(position.weight_pct) || 0), 0);
}

export default function AdvisoryInputForm({
  feature,
  form,
  assets = [],
  isLoadingAssets = false,
  assetLoadError = "",
  isSubmitting,
  isDisabled = false,
  onChange,
  onSubmit,
}) {
  const isTickerList = feature.inputMode === "tickers";
  const isSingleTicker = feature.inputMode === "ticker";
  const isPositions = feature.inputMode === "positions";
  const isOwnedAsset = feature.inputMode === "owned_asset";

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

  function updateProxy(index, field, value) {
    onChange({
      ...form,
      customProxies: form.customProxies.map((proxy, proxyIndex) =>
        proxyIndex === index ? { ...proxy, [field]: value } : proxy,
      ),
    });
  }

  function addProxy() {
    onChange({ ...form, customProxies: [...form.customProxies, { sector: "", ticker: "" }] });
  }

  function removeProxy(index) {
    onChange({
      ...form,
      customProxies: form.customProxies.filter((_, proxyIndex) => proxyIndex !== index),
    });
  }

  const advancedField = (label, id, field, { hint, ...inputOptions } = {}) => (
    <label className="advisory-field" htmlFor={id}>
      <span>{label}</span>
      <input
        aria-label={label}
        id={id}
        value={form[field]}
        onChange={(event) => onChange({ ...form, [field]: event.target.value })}
        {...inputOptions}
      />
      {hint && <small>{hint}</small>}
    </label>
  );

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
              {feature.id === "high_upside_speculative_stocks" &&
                " 비상장 스타트업은 제외하며 결과는 모두 추가 조사용 관찰 후보입니다."}
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
        {isOwnedAsset && (
          <div className="advisory-owned-asset-fields">
            <label className="advisory-field" htmlFor="advisory-owned-asset">
              <span>이익실현을 검토할 보유 자산</span>
              <select
                aria-label="이익실현을 검토할 보유 자산"
                aria-required="true"
                disabled={isLoadingAssets || !assets.length}
                id="advisory-owned-asset"
                value={form.asset_id}
                onChange={(event) => onChange({ ...form, asset_id: event.target.value })}
              >
                <option value="">
                  {isLoadingAssets
                    ? "보유 자산을 불러오는 중입니다"
                    : assets.length
                      ? "보유 자산을 선택하세요"
                      : "선택 가능한 보유 자산이 없습니다"}
                </option>
                {assets.map((asset) => (
                  <option key={asset.id} value={asset.id}>
                    {asset.name || asset.ticker} ({asset.ticker})
                  </option>
                ))}
              </select>
              {assetLoadError ? (
                <small className="alert">{assetLoadError}</small>
              ) : assets.length ? (
                <small>
                  보유 수량과 평균단가, 현재가는 저장된 자산 및 시장 데이터로만 확인합니다.
                </small>
              ) : (
                <small>자산 탭에서 수량이 있는 주식 또는 ETF를 먼저 등록해 주세요.</small>
              )}
            </label>
            <label className="advisory-field" htmlFor="advisory-review-horizon">
              <span>검토 기간</span>
              <select
                id="advisory-review-horizon"
                value={form.review_horizon}
                onChange={(event) => onChange({ ...form, review_horizon: event.target.value })}
              >
                <option value="short">단기</option>
                <option value="medium">중기</option>
                <option value="long">장기</option>
              </select>
              <small>기본값은 중기입니다. 주문 수량이나 가격을 입력하지 않습니다.</small>
            </label>
            <p className="field-hint advisory-independence-note">
              기존 리포트 의견은 비교 정보로만 표시하며, 이번 이익실현 판단 점수에는 반영하지
              않습니다.
            </p>
          </div>
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
        {feature.id === "undervalued_us_stocks" && (
          <div className="advisory-advanced-fields">
            {advancedField(
              "최소 시가총액 (USD, 선택)",
              "advisory-min-market-cap",
              "min_market_cap_usd",
              {
                inputMode: "numeric",
                min: "0",
                placeholder: "예: 10000000000",
                step: "1",
                type: "number",
                hint: "비워 두면 시가총액 필터를 적용하지 않습니다.",
              },
            )}
          </div>
        )}
        {feature.id === "post_earnings_opportunities" && (
          <div className="advisory-advanced-fields">
            {advancedField(
              "실적 발표 조회 기간 (일, 선택)",
              "advisory-earnings-lookback",
              "lookback_days",
              {
                inputMode: "numeric",
                max: "90",
                min: "1",
                placeholder: "기본값 14",
                step: "1",
                type: "number",
                hint: "비워 두면 백엔드 기본값 14일을 사용합니다.",
              },
            )}
          </div>
        )}
        {feature.id === "ai_beneficiaries" && (
          <label className="advisory-field" htmlFor="advisory-themes">
            <span>AI 테마 (선택)</span>
            <input
              id="advisory-themes"
              placeholder="예: inference, data center, power infrastructure"
              value={form.themes}
              onChange={(event) => onChange({ ...form, themes: event.target.value })}
            />
            <small>쉼표 또는 줄바꿈으로 최대 20개까지 입력할 수 있습니다.</small>
          </label>
        )}
        {feature.id === "high_dividend_etfs" && (
          <div className="advisory-advanced-fields">
            {advancedField(
              "최소 분배수익률 (%, 선택)",
              "advisory-min-distribution-yield",
              "min_distribution_yield_percent",
              {
                inputMode: "decimal",
                max: "100",
                min: "0",
                placeholder: "예: 3.5",
                step: "0.1",
                type: "number",
                hint: "비워 두면 최소 수익률 필터를 적용하지 않습니다.",
              },
            )}
          </div>
        )}
        {feature.id === "sec_filing_risk" && (
          <div className="advisory-advanced-fields">
            {advancedField(
              "SEC 공시 조회 기간 (일, 선택)",
              "advisory-sec-lookback",
              "lookback_days",
              {
                inputMode: "numeric",
                max: "365",
                min: "1",
                placeholder: "기본값 365",
                step: "1",
                type: "number",
                hint: "비워 두면 최근 365일 공시를 확인합니다.",
              },
            )}
          </div>
        )}
        {feature.id === "sector_outlook" && (
          <div className="advisory-proxies">
            <div className="advisory-position-heading">
              <strong>사용자 지정 섹터 프록시 (선택)</strong>
              <span>섹터별 ETF 티커</span>
            </div>
            {form.customProxies.map((proxy, index) => (
              <div className="advisory-proxy-row" key={`${index}-${proxy.sector}-${proxy.ticker}`}>
                <label>
                  <span className="sr-only">섹터명 {index + 1}</span>
                  <input
                    aria-label={`섹터명 ${index + 1}`}
                    placeholder="예: 반도체"
                    value={proxy.sector}
                    onChange={(event) => updateProxy(index, "sector", event.target.value)}
                  />
                </label>
                <label>
                  <span className="sr-only">프록시 ETF 티커 {index + 1}</span>
                  <input
                    aria-label={`프록시 ETF 티커 ${index + 1}`}
                    placeholder="예: SOXX"
                    value={proxy.ticker}
                    onChange={(event) => updateProxy(index, "ticker", event.target.value)}
                  />
                </label>
                <button
                  aria-label={`프록시 ${index + 1} 제거`}
                  className="secondary-action compact-action"
                  disabled={form.customProxies.length === 1}
                  type="button"
                  onClick={() => removeProxy(index)}
                >
                  제거
                </button>
              </div>
            ))}
            <button className="secondary-action compact-action" type="button" onClick={addProxy}>
              프록시 추가
            </button>
            <p className="field-hint">
              비워 두면 기본 섹터 프록시를 사용합니다. 입력값은 같은 섹터명의 기본 ETF를 대체하거나
              새 섹터를 추가합니다.
            </p>
          </div>
        )}
        {feature.inputMode === "none" && (
          <p className="field-hint">
            기본 10개 섹터를 분석하며 사용자 프록시로 일부를 바꿀 수 있습니다.
          </p>
        )}
        <div className="advisory-submit-row">
          <p className="field-hint">
            결과는 투자 정보이며 자동매매·주문 실행 기능을 제공하지 않습니다.
          </p>
          <button disabled={isSubmitting || isDisabled} type="submit">
            {isSubmitting ? "AI 자문 요청 중…" : "AI 자문 요청"}
          </button>
        </div>
      </form>
    </section>
  );
}
