import React from "react";
import { createRoot } from "react-dom/client";

import App from "./App.jsx";
import "./styles/global.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// PWA: 프로덕션 빌드에서만 앱 셸 서비스워커를 등록한다 (Phase 6-4).
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register(`${import.meta.env.BASE_URL}sw.js`).catch(() => {
      // 등록 실패(비보안 컨텍스트 등)는 앱 동작에 영향을 주지 않는다.
    });
  });
}
