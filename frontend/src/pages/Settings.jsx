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
        frontend_timezone: settings.frontend_timezone,
        stale_data_business_days: Number(settings.stale_data_business_days),
      });
      setSettings(saved);
      setStatus("Saved");
    } catch (err) {
      setStatus(err.message);
    }
  }

  if (!settings) {
    return (
      <section className="page">
        <p className="empty-state">Loading settings.</p>
      </section>
    );
  }

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>Settings</h1>
          <p>Report timing, AI model, and risk profile.</p>
        </div>
      </header>
      {status && <p className="notice">{status}</p>}
      <section className="panel">
        <form className="settings-form" onSubmit={save}>
          <label>
            Domestic report time
            <input
              value={settings.domestic_report_time}
              onChange={(event) => update("domestic_report_time", event.target.value)}
            />
          </label>
          <label>
            Global report time
            <input
              value={settings.global_report_time}
              onChange={(event) => update("global_report_time", event.target.value)}
            />
          </label>
          <label>
            AI provider
            <input value={settings.ai_provider} onChange={(event) => update("ai_provider", event.target.value)} />
          </label>
          <label>
            AI model
            <input value={settings.ai_model} onChange={(event) => update("ai_model", event.target.value)} />
          </label>
          <label>
            Risk profile
            <select value={settings.risk_profile} onChange={(event) => update("risk_profile", event.target.value)}>
              <option value="conservative">conservative</option>
              <option value="balanced">balanced</option>
              <option value="aggressive">aggressive</option>
            </select>
          </label>
          <label>
            Frontend timezone
            <input
              value={settings.frontend_timezone}
              onChange={(event) => update("frontend_timezone", event.target.value)}
            />
          </label>
          <label>
            Stale data business days
            <input
              min="0"
              type="number"
              value={settings.stale_data_business_days}
              onChange={(event) => update("stale_data_business_days", event.target.value)}
            />
          </label>
          <label>
            API base URL
            <input readOnly value={API_BASE_URL} />
          </label>
          <button type="submit">Save settings</button>
        </form>
      </section>
    </section>
  );
}
