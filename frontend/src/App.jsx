import { useState } from "react";

import { clearApiAccessToken, getApiAccessToken } from "./api/client.js";
import AccessGate from "./components/AccessGate.jsx";
import Assets from "./pages/Assets.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Reports from "./pages/Reports.jsx";
import Settings from "./pages/Settings.jsx";

const tabs = [
  { id: "dashboard", label: "대시보드" },
  { id: "assets", label: "자산" },
  { id: "reports", label: "리포트" },
  { id: "settings", label: "설정" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [isUnlocked, setIsUnlocked] = useState(Boolean(getApiAccessToken()));
  const Page = {
    dashboard: Dashboard,
    assets: Assets,
    reports: Reports,
    settings: Settings,
  }[activeTab];

  if (!isUnlocked) {
    return <AccessGate onUnlock={() => setIsUnlocked(true)} />;
  }

  function lock() {
    clearApiAccessToken();
    setIsUnlocked(false);
    setActiveTab("dashboard");
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <strong>AlphaPilot</strong>
          <span>개인 투자 전략가</span>
        </div>
        <nav>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={activeTab === tab.id ? "active" : ""}
              type="button"
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
        <button className="lock-button" type="button" onClick={lock}>
          잠금
        </button>
      </aside>
      <main>
        <Page />
      </main>
    </div>
  );
}
