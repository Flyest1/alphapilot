import { useEffect, useState } from "react";

import { api } from "../api/client.js";
import { formatReportTime } from "../api/reports.js";

function statusText(value) {
  return value ? "정상" : "확인 필요";
}

export default function Status() {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  function loadStatus() {
    setIsLoading(true);
    setError("");
    api.system
      .status()
      .then(setStatus)
      .catch((err) => setError(err.message))
      .finally(() => setIsLoading(false));
  }

  useEffect(() => {
    loadStatus();
  }, []);

  const databaseOk = status?.database?.status === "ok";

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <h1>상태</h1>
          <p>백엔드, 데이터베이스, OpenAI 설정과 최근 리포트 상태를 확인합니다.</p>
        </div>
        <div className="header-actions">
          <button disabled={isLoading} type="button" onClick={loadStatus}>
            새로고침
          </button>
        </div>
      </header>
      {error && <p className="alert">{error}</p>}
      {isLoading && <p className="empty-state">상태를 확인하는 중입니다.</p>}
      {status && (
        <>
          <section className="panel">
            <div className="metric-grid compact">
              <div>
                <span>백엔드</span>
                <strong>{status.backend?.status === "ok" ? "정상" : "확인 필요"}</strong>
              </div>
              <div>
                <span>실행 환경</span>
                <strong>{status.backend?.app_env || "-"}</strong>
              </div>
              <div>
                <span>데이터베이스</span>
                <strong>{databaseOk ? "정상" : "오류"}</strong>
              </div>
              <div>
                <span>저장소</span>
                <strong>{status.database?.provider || "-"}</strong>
              </div>
              <div>
                <span>OpenAI 키</span>
                <strong>{statusText(status.openai?.configured)}</strong>
              </div>
              <div>
                <span>자산</span>
                <strong>{status.assets?.total_count ?? 0}</strong>
              </div>
              <div>
                <span>활성 후보</span>
                <strong>{status.candidate_assets?.active_count ?? 0}</strong>
              </div>
              <div>
                <span>리포트</span>
                <strong>{status.reports?.total_count ?? 0}</strong>
              </div>
            </div>
          </section>

          <section className="panel">
            <h2>최근 리포트</h2>
            <div className="metric-grid compact">
              <div>
                <span>국내 리포트</span>
                <strong>{formatReportTime(status.reports?.latest_domestic_created_at)}</strong>
              </div>
              <div>
                <span>글로벌 리포트</span>
                <strong>{formatReportTime(status.reports?.latest_global_created_at)}</strong>
              </div>
              <div>
                <span>후보군 전체</span>
                <strong>{status.candidate_assets?.total_count ?? 0}</strong>
              </div>
              <div>
                <span>Supabase 설정</span>
                <strong>{statusText(status.database?.configured)}</strong>
              </div>
            </div>
            {status.database?.error && <p className="alert">{status.database.error}</p>}
          </section>
        </>
      )}
    </section>
  );
}
