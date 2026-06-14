import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client.js";
import Skeleton from "../components/Skeleton.jsx";

const EVENT_LABELS = {
  report_completed: "리포트 완료",
  target_hit: "목표 도달",
  stop_hit: "손절 도달",
  cycle_closed: "cycle 종료",
  drift_warning: "드리프트 경고",
};
const noop = () => {};

function displayTime(value) {
  if (!value) return "-";
  return new Date(value).toLocaleString("ko-KR");
}

export default function Notifications({ onUnreadCountChange = noop }) {
  const [data, setData] = useState({ notifications: [], unread_count: 0 });
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const result = await api.notifications.list();
      setData(result);
      onUnreadCountChange(result.unread_count);
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }, [onUnreadCountChange]);

  useEffect(() => {
    load();
  }, [load]);

  async function markRead(notification) {
    if (notification.is_read) return;
    await api.notifications.read(notification.id);
    await load();
  }

  async function markAllRead() {
    await api.notifications.readAll();
    await load();
  }

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>알림 센터</h1>
          <p>스케줄 리포트의 완료, 추천 cycle 종료, 리밸런스 경고를 확인합니다.</p>
        </div>
        <div className="header-actions">
          <button
            disabled={isLoading || data.unread_count === 0}
            type="button"
            onClick={markAllRead}
          >
            모두 읽음
          </button>
          <button disabled={isLoading} type="button" onClick={load}>
            새로고침
          </button>
        </div>
      </header>
      {error && <p className="alert">{error}</p>}
      {isLoading && <Skeleton label="알림을 불러오는 중입니다." lines={4} />}
      {!isLoading && data.notifications.length === 0 && (
        <p className="empty-state">아직 생성된 알림이 없습니다.</p>
      )}
      <div className="notification-list">
        {data.notifications.map((notification) => (
          <button
            className={`notification-card ${notification.is_read ? "read" : "unread"}`}
            key={notification.id}
            type="button"
            onClick={() => markRead(notification)}
          >
            <div className="notification-card-header">
              <span
                className={`status-pill ${notification.severity === "warning" ? "warning" : ""}`}
              >
                {EVENT_LABELS[notification.event_type] || notification.event_type}
              </span>
              <span>{displayTime(notification.created_at)}</span>
            </div>
            <strong>{notification.title}</strong>
            <span>{notification.message}</span>
            <small>
              {notification.is_read ? "읽음" : "읽지 않음"} · Telegram{" "}
              {notification.telegram_status}
            </small>
          </button>
        ))}
      </div>
    </section>
  );
}
