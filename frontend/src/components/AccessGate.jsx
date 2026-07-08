import { useState } from "react";

import { API_BASE_URL, apiRequest, setApiAccessToken } from "../api/client.js";

export default function AccessGate({ onUnlock }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [isChecking, setIsChecking] = useState(false);

  async function submit(event) {
    event.preventDefault();
    const trimmed = token.trim();
    if (!trimmed) {
      setError("백엔드 서버에 설정한 API_ACCESS_TOKEN 값을 입력하세요.");
      return;
    }
    setIsChecking(true);
    setError("");
    try {
      await apiRequest("/api/settings", { accessToken: trimmed });
      setApiAccessToken(trimmed);
      onUnlock();
    } catch (err) {
      if (err.status === 401 || err.status === 403) {
        setError(
          `현재 API URL(${API_BASE_URL})에서 토큰을 거부했습니다. 입력한 토큰이 현재 백엔드 서버의 API_ACCESS_TOKEN과 일치하는지 확인하세요.`,
        );
      } else {
        setError(
          `현재 API URL(${API_BASE_URL})에 연결할 수 없습니다. 백엔드 실행 상태를 확인하세요.`,
        );
      }
    } finally {
      setIsChecking(false);
    }
  }

  return (
    <main className="access-screen">
      <section className="access-panel">
        <div>
          <strong>AlphaPilot</strong>
          <h1>접속 토큰 입력</h1>
          <p>
            백엔드 서버 환경 변수에 저장한 API_ACCESS_TOKEN을 입력해야 자산과 리포트를 볼 수
            있습니다.
          </p>
        </div>
        <form onSubmit={submit}>
          <label>
            API_ACCESS_TOKEN
            <input
              autoComplete="off"
              placeholder="백엔드에 저장한 긴 랜덤 문자열"
              type="password"
              value={token}
              onChange={(event) => setToken(event.target.value)}
            />
          </label>
          <button disabled={isChecking} type="submit">
            {isChecking ? "확인 중" : "접속"}
          </button>
        </form>
        <p className="field-hint">API 기준 URL: {API_BASE_URL}</p>
        {error && <p className="alert">{error}</p>}
      </section>
    </main>
  );
}
