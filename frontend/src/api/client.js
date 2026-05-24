const rawApiBaseUrl = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
export const API_BASE_URL = rawApiBaseUrl.replace(/\/+$/, "");
const API_ACCESS_TOKEN = import.meta.env.VITE_API_ACCESS_TOKEN || "";

export async function apiRequest(path, options = {}) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${normalizedPath}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${API_ACCESS_TOKEN}`,
        ...(options.headers || {}),
      },
    });
  } catch (error) {
    throw new Error("백엔드 연결에 실패했습니다. API URL, 토큰, CORS 설정을 확인하세요.");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "요청에 실패했습니다." }));
    throw new Error(body.detail || "요청에 실패했습니다.");
  }

  return response.json();
}

export const api = {
  assets: {
    list: () => apiRequest("/api/assets"),
    create: (payload) =>
      apiRequest("/api/assets", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    update: (id, payload) =>
      apiRequest(`/api/assets/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    remove: (id) => apiRequest(`/api/assets/${id}`, { method: "DELETE" }),
  },
  portfolio: {
    summary: () => apiRequest("/api/portfolio/summary"),
  },
  reports: {
    latest: () => apiRequest("/api/reports/latest"),
    list: () => apiRequest("/api/reports"),
    get: (id) => apiRequest(`/api/reports/${id}`),
  },
  performanceLogs: {
    list: () => apiRequest("/api/performance-logs"),
  },
  settings: {
    get: () => apiRequest("/api/settings"),
    save: (payload) =>
      apiRequest("/api/settings", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
  },
};
