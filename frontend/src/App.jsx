import { useEffect, useState } from "react";

import { api, clearApiAccessToken, getApiAccessToken } from "./api/client.js";
import AccessGate from "./components/AccessGate.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import Assets from "./pages/Assets.jsx";
import Comparison from "./pages/Comparison.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Performance from "./pages/Performance.jsx";
import Notifications from "./pages/Notifications.jsx";
import Reports from "./pages/Reports.jsx";
import Settings from "./pages/Settings.jsx";
import Status from "./pages/Status.jsx";

const tabs = [
  { id: "dashboard", label: "대시보드" },
  { id: "assets", label: "자산" },
  { id: "reports", label: "리포트" },
  { id: "comparison", label: "비교" },
  { id: "performance", label: "성과 분석" },
  { id: "notifications", label: "알림" },
  { id: "status", label: "상태" },
  { id: "settings", label: "설정" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [isUnlocked, setIsUnlocked] = useState(Boolean(getApiAccessToken()));
  const [unreadCount, setUnreadCount] = useState(0);
  const Page = {
    dashboard: Dashboard,
    assets: Assets,
    comparison: Comparison,
    performance: Performance,
    notifications: Notifications,
    reports: Reports,
    status: Status,
    settings: Settings,
  }[activeTab];

  useEffect(() => {
    if (!isUnlocked) return undefined;
    let cancelled = false;
    async function refreshUnreadCount() {
      try {
        const result = await api.notifications.list(true, 1);
        if (!cancelled) setUnreadCount(result.unread_count);
      } catch (_error) {
        // 알림 배지 실패는 다른 화면 사용을 막지 않는다.
      }
    }
    refreshUnreadCount();
    const intervalId = window.setInterval(refreshUnreadCount, 60 * 1000);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [isUnlocked]);

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
              {tab.id === "notifications" && unreadCount > 0 && (
                <span className="notification-badge">{unreadCount > 99 ? "99+" : unreadCount}</span>
              )}
            </button>
          ))}
        </nav>
        <button className="lock-button" type="button" onClick={lock}>
          잠금
        </button>
      </aside>
      <main>
        <ErrorBoundary resetKey={activeTab}>
          <Page onUnreadCountChange={setUnreadCount} />
        </ErrorBoundary>
      </main>
    </div>
  );
}
