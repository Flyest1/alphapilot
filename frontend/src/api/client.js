const rawApiBaseUrl = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
export const API_BASE_URL = rawApiBaseUrl.replace(/\/+$/, "");
export const API_ACCESS_TOKEN_STORAGE_KEY = "alphapilot_api_access_token";
const API_CACHE_PREFIX = "alphapilot_api_cache:";

export function getApiAccessToken() {
  return window.localStorage.getItem(API_ACCESS_TOKEN_STORAGE_KEY) || "";
}

export function setApiAccessToken(token) {
  window.localStorage.setItem(API_ACCESS_TOKEN_STORAGE_KEY, token.trim());
}

export function clearApiAccessToken() {
  window.localStorage.removeItem(API_ACCESS_TOKEN_STORAGE_KEY);
  clearApiCache();
}

function cacheKey(path) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_CACHE_PREFIX}${API_BASE_URL}${normalizedPath}`;
}

export function readApiCache(path) {
  try {
    const cached = window.localStorage.getItem(cacheKey(path));
    if (!cached) return null;
    return JSON.parse(cached).data ?? null;
  } catch (_error) {
    return null;
  }
}

function writeApiCache(path, data) {
  try {
    window.localStorage.setItem(
      cacheKey(path),
      JSON.stringify({ cached_at: new Date().toISOString(), data }),
    );
  } catch (_error) {
    // Browser storage can be full or unavailable; the app should still work without cache.
  }
}

export function clearApiCache() {
  const keys = [];
  for (let index = 0; index < window.localStorage.length; index += 1) {
    const key = window.localStorage.key(index);
    if (key?.startsWith(API_CACHE_PREFIX)) keys.push(key);
  }
  keys.forEach((key) => window.localStorage.removeItem(key));
}

export async function apiRequest(path, options = {}) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const accessToken = options.accessToken ?? getApiAccessToken();
  const { accessToken: _accessToken, ...fetchOptions } = options;
  const method = (fetchOptions.method || "GET").toUpperCase();
  if (!accessToken) {
    throw new Error("접속 토큰을 먼저 입력하세요.");
  }
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${normalizedPath}`, {
      ...fetchOptions,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${accessToken}`,
        ...(fetchOptions.headers || {}),
      },
    });
  } catch (error) {
    throw new Error("백엔드 연결에 실패했습니다. API URL, 토큰, CORS 설정을 확인하세요.");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "요청에 실패했습니다." }));
    throw new Error(body.detail || "요청에 실패했습니다.");
  }

  const data = await response.json();
  if (method === "GET") {
    writeApiCache(normalizedPath, data);
  } else {
    clearApiCache();
  }
  return data;
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
  candidates: {
    list: () => apiRequest("/api/candidates"),
    create: (payload) =>
      apiRequest("/api/candidates", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    update: (id, payload) =>
      apiRequest(`/api/candidates/${id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    remove: (id) => apiRequest(`/api/candidates/${id}`, { method: "DELETE" }),
  },
  portfolio: {
    summary: () => apiRequest("/api/portfolio/summary"),
  },
  reports: {
    latest: () => apiRequest("/api/reports/latest"),
    list: () => apiRequest("/api/reports"),
    get: (id) => apiRequest(`/api/reports/${id}`),
    generate: (reportType) =>
      apiRequest(`/api/reports/${reportType}/manual-generate`, { method: "POST" }),
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
  system: {
    status: () => apiRequest("/api/system/status"),
  },
};
