import { useEffect, useState } from "react";

import { API_BASE_URL, api } from "../api/client.js";
import CandidateAssetsPanel from "../components/CandidateAssetsPanel.jsx";

function roundNumber(value, digits = 4) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  return Number(numeric.toFixed(digits));
}

function normalizeSettings(settings) {
  return {
    ...settings,
    usd_krw_rate: roundNumber(settings.usd_krw_rate, 4),
  };
}

export default function Settings() {
  const [settings, setSettings] = useState(null);
  const [status, setStatus] = useState("");

  useEffect(() => {
    api.settings
      .get()
      .then((data) => setSettings(normalizeSettings(data)))
      .catch((err) => setStatus(err.message));
  }, []);

  function update(field, value) {
    setSettings((current) => ({ ...current, [field]: value }));
  }

  async function save(event) {
    event.preventDefault();
    setStatus("");
    try {
      const saved = await api.settings.save({
        domestic_report_time: settings.domestic_report_time,
        global_report_time: settings.global_report_time,
        ai_provider: settings.ai_provider,
        ai_model: settings.ai_model,
        risk_profile: settings.risk_profile,
        candidate_horizon: settings.candidate_horizon,
        frontend_timezone: settings.frontend_timezone,
        stale_data_business_days: Number(settings.stale_data_business_days),
        usd_krw_rate: roundNumber(settings.usd_krw_rate, 4),
        target_domestic_pct: Number(settings.target_domestic_pct),
        target_global_pct: Number(settings.target_global_pct),
        target_cash_pct: Number(settings.target_cash_pct),
        target_max_asset_pct: Number(settings.target_max_asset_pct),
        rebalance_band_pct: Number(settings.rebalance_band_pct),
        risk_per_trade_pct: Number(settings.risk_per_trade_pct),
        fee_rate_pct: Number(settings.fee_rate_pct),
        kr_tax_rate_pct: Number(settings.kr_tax_rate_pct),
        fx_spread_pct: Number(settings.fx_spread_pct),
      });
      setSettings(normalizeSettings(saved));
      setStatus("설정을 저장했습니다.");
    } catch (err) {
      setStatus(err.message);
    }
  }

  if (!settings) {
    return (
      <section className="page">
        <p className="empty-state">설정을 불러오는 중입니다.</p>
      </section>
    );
  }

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>설정</h1>
          <p>리포트 생성 시간, AI 모델, 위험 성향을 관리합니다.</p>
        </div>
      </header>
      {status && <p className="notice">{status}</p>}
      <section className="panel">
        <form className="settings-form" onSubmit={save}>
          <label>
            국내 리포트 시간
            <input
              value={settings.domestic_report_time}
              onChange={(event) => update("domestic_report_time", event.target.value)}
            />
          </label>
          <label>
            글로벌 리포트 시간
            <input
              value={settings.global_report_time}
              onChange={(event) => update("global_report_time", event.target.value)}
            />
          </label>
          <label>
            AI 제공자
            <input
              value={settings.ai_provider}
              onChange={(event) => update("ai_provider", event.target.value)}
            />
          </label>
          <label>
            AI 모델
            <input
              value={settings.ai_model}
              onChange={(event) => update("ai_model", event.target.value)}
            />
          </label>
          <label>
            위험 성향
            <select
              value={settings.risk_profile}
              onChange={(event) => update("risk_profile", event.target.value)}
            >
              <option value="conservative">보수적</option>
              <option value="balanced">균형</option>
              <option value="aggressive">공격적</option>
            </select>
          </label>
          <label>
            추가 매수 후보 목표 기간
            <select
              value={settings.candidate_horizon}
              onChange={(event) => update("candidate_horizon", event.target.value)}
            >
              <option value="short">단기 - 약 5거래일</option>
              <option value="medium">중기 - 약 20거래일</option>
              <option value="long">장기 - 약 60거래일</option>
            </select>
          </label>
          <label>
            화면 시간대
            <input
              value={settings.frontend_timezone}
              onChange={(event) => update("frontend_timezone", event.target.value)}
            />
          </label>
          <label>
            데이터 지연 허용 영업일
            <input
              min="0"
              type="number"
              value={settings.stale_data_business_days}
              onChange={(event) => update("stale_data_business_days", event.target.value)}
            />
          </label>
          <label>
            USD-KRW 환율
            <input
              min="1"
              step="any"
              type="number"
              value={settings.usd_krw_rate}
              onChange={(event) => update("usd_krw_rate", event.target.value)}
            />
            <span className="field-hint">대시보드 총액을 KRW로 환산할 때 사용합니다.</span>
          </label>
          <label>
            API 기준 URL
            <input readOnly value={API_BASE_URL} />
          </label>
          <button type="submit">설정 저장</button>
        </form>
      </section>
      <section className="panel">
        <div className="section-heading">
          <div>
            <h2>목표 배분과 리스크 (Phase 5)</h2>
            <p>대시보드 드리프트 카드와 신규 후보 제안 투입 한도 계산에 사용합니다.</p>
          </div>
        </div>
        <form className="settings-form" onSubmit={save}>
          <label>
            목표 국내 비중 (%)
            <input
              max="100"
              min="0"
              step="any"
              type="number"
              value={settings.target_domestic_pct}
              onChange={(event) => update("target_domestic_pct", event.target.value)}
            />
          </label>
          <label>
            목표 글로벌 비중 (%)
            <input
              max="100"
              min="0"
              step="any"
              type="number"
              value={settings.target_global_pct}
              onChange={(event) => update("target_global_pct", event.target.value)}
            />
          </label>
          <label>
            목표 현금 비중 (%)
            <input
              max="100"
              min="0"
              step="any"
              type="number"
              value={settings.target_cash_pct}
              onChange={(event) => update("target_cash_pct", event.target.value)}
            />
            <span className="field-hint">세 비중의 합계가 100이 되도록 입력하세요.</span>
          </label>
          <label>
            종목별 비중 상한 (%)
            <input
              max="100"
              min="1"
              step="any"
              type="number"
              value={settings.target_max_asset_pct}
              onChange={(event) => update("target_max_asset_pct", event.target.value)}
            />
          </label>
          <label>
            리밸런스 임계치 (%p)
            <input
              max="50"
              min="0"
              step="any"
              type="number"
              value={settings.rebalance_band_pct}
              onChange={(event) => update("rebalance_band_pct", event.target.value)}
            />
            <span className="field-hint">
              목표 대비 드리프트가 이 값을 넘으면 제안이 표시됩니다.
            </span>
          </label>
          <label>
            1회 리스크 한도 (총자산 %)
            <input
              max="10"
              min="0.1"
              step="any"
              type="number"
              value={settings.risk_per_trade_pct}
              onChange={(event) => update("risk_per_trade_pct", event.target.value)}
            />
            <span className="field-hint">신규 후보 제안 투입 한도 계산에 사용합니다.</span>
          </label>
          <label>
            매매 수수료율 (편도 %)
            <input
              max="5"
              min="0"
              step="any"
              type="number"
              value={settings.fee_rate_pct}
              onChange={(event) => update("fee_rate_pct", event.target.value)}
            />
          </label>
          <label>
            국내 거래세율 (매도 %)
            <input
              max="5"
              min="0"
              step="any"
              type="number"
              value={settings.kr_tax_rate_pct}
              onChange={(event) => update("kr_tax_rate_pct", event.target.value)}
            />
          </label>
          <label>
            환전 스프레드 (편도 %)
            <input
              max="5"
              min="0"
              step="any"
              type="number"
              value={settings.fx_spread_pct}
              onChange={(event) => update("fx_spread_pct", event.target.value)}
            />
            <span className="field-hint">USD 자산의 비용 차감 수익률 추정에 사용합니다.</span>
          </label>
          <button type="submit">설정 저장</button>
        </form>
      </section>
      <CandidateAssetsPanel />
    </section>
  );
}
