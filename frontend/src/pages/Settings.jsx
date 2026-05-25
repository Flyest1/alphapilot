import { useEffect, useState } from "react";

import { API_BASE_URL, api } from "../api/client.js";

export default function Settings() {
  const [settings, setSettings] = useState(null);
  const [status, setStatus] = useState("");

  useEffect(() => {
    api.settings.get().then(setSettings).catch((err) => setStatus(err.message));
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
      });
      setSettings(saved);
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
            <input value={settings.ai_provider} onChange={(event) => update("ai_provider", event.target.value)} />
          </label>
          <label>
            AI 모델
            <input value={settings.ai_model} onChange={(event) => update("ai_model", event.target.value)} />
          </label>
          <label>
            위험 성향
            <select value={settings.risk_profile} onChange={(event) => update("risk_profile", event.target.value)}>
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
            API 기준 URL
            <input readOnly value={API_BASE_URL} />
          </label>
          <button type="submit">설정 저장</button>
        </form>
      </section>
    </section>
  );
}
