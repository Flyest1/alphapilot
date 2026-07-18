import { lazy, Suspense, useEffect, useState } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

import { api, clearApiAccessToken, getApiAccessToken } from "./api/client.js";
import AccessGate from "./components/AccessGate.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";

const pages = {
  dashboard: lazy(() => import("./pages/Dashboard.jsx")),
  advisory: lazy(() => import("./pages/Advisory.jsx")),
  assets: lazy(() => import("./pages/Assets.jsx")),
  comparison: lazy(() => import("./pages/Comparison.jsx")),
  performance: lazy(() => import("./pages/Performance.jsx")),
  notifications: lazy(() => import("./pages/Notifications.jsx")),
  reports: lazy(() => import("./pages/Reports.jsx")),
  status: lazy(() => import("./pages/Status.jsx")),
  settings: lazy(() => import("./pages/Settings.jsx")),
};

const tabs = [
  { id: "dashboard", label: "대시보드" },
  { id: "advisory", label: "AI 자문" },
  { id: "assets", label: "자산" },
  { id: "reports", label: "리포트" },
  { id: "comparison", label: "비교" },
  { id: "performance", label: "성과 분석" },
  { id: "notifications", label: "알림" },
  { id: "status", label: "상태" },
  { id: "settings", label: "설정" },
];

gsap.registerPlugin(ScrollTrigger);

function shouldReduceMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [isUnlocked, setIsUnlocked] = useState(Boolean(getApiAccessToken()));
  const [unreadCount, setUnreadCount] = useState(0);
  const Page = pages[activeTab];

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

  useEffect(() => {
    if (!isUnlocked || shouldReduceMotion()) return undefined;

    const ctx = gsap.context(() => {
      gsap.fromTo(
        ".motion-nav",
        { autoAlpha: 0, y: -18 },
        { autoAlpha: 1, y: 0, duration: 0.5, ease: "power3.out" },
      );
      gsap.fromTo(
        ".motion-content",
        { autoAlpha: 0, y: 18 },
        { autoAlpha: 1, y: 0, duration: 0.6, ease: "power3.out" },
      );
    });

    return () => ctx.revert();
  }, [isUnlocked]);

  useEffect(() => {
    if (!isUnlocked || shouldReduceMotion()) return undefined;

    const ctx = gsap.context(() => {
      gsap.utils
        .toArray(".motion-content .panel, .motion-content .summary-card")
        .forEach((item) => {
          gsap.fromTo(
            item,
            { autoAlpha: 0.78, y: 18, scale: 0.985 },
            {
              autoAlpha: 1,
              y: 0,
              scale: 1,
              duration: 0.55,
              ease: "power3.out",
              scrollTrigger: {
                trigger: item,
                start: "top 88%",
                once: true,
              },
            },
          );
        });
      gsap.fromTo(
        ".motion-content .page > *",
        { autoAlpha: 0, y: 18, filter: "blur(6px)" },
        {
          autoAlpha: 1,
          y: 0,
          filter: "blur(0px)",
          duration: 0.48,
          ease: "power3.out",
          stagger: 0.03,
        },
      );
    });

    return () => ctx.revert();
  }, [activeTab, isUnlocked]);

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
      <header className="topbar motion-nav">
        <div className="brand">
          <strong>AlphaPilot</strong>
          <span>Market cockpit</span>
        </div>
        <nav className="primary-nav" aria-label="주요 메뉴">
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
      </header>
      <main className="motion-content">
        <ErrorBoundary resetKey={activeTab}>
          <Suspense fallback={<p className="empty-state">화면을 불러오는 중입니다.</p>}>
            <Page onUnreadCountChange={setUnreadCount} />
          </Suspense>
        </ErrorBoundary>
      </main>
    </div>
  );
}
