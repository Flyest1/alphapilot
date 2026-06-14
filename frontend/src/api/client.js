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

function readApiCacheEntry(path) {
  try {
    const cached = window.localStorage.getItem(cacheKey(path));
    if (!cached) return null;
    return JSON.parse(cached);
  } catch (_error) {
    return null;
  }
}

export function readApiCache(path, options = {}) {
  const entry = readApiCacheEntry(path);
  if (!entry) return null;
  if (options.maxAgeMs && !isApiCacheFresh(path, options.maxAgeMs)) return null;
  return entry.data ?? null;
}

export function isApiCacheFresh(path, maxAgeMs) {
  const entry = readApiCacheEntry(path);
  if (!entry?.cached_at) return false;
  return Date.now() - new Date(entry.cached_at).getTime() <= maxAgeMs;
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

export const DEFAULT_TIMEOUT_MS = 30 * 1000;

// 표준 에러 객체: message 외에 status(HTTP 코드)와 kind(분류)를 함께 제공한다.
export class ApiError extends Error {
  constructor(message, { status = 0, kind = "http" } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.kind = kind; // "http" | "network" | "timeout" | "auth"
  }
}

async function fetchWithTimeout(url, fetchOptions, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...fetchOptions, signal: controller.signal });
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new ApiError(
        "요청 시간이 초과되었습니다. 백엔드가 깨어나는 중일 수 있으니 잠시 후 다시 시도하세요.",
        { kind: "timeout" },
      );
    }
    throw new ApiError("백엔드 연결에 실패했습니다. API URL, 토큰, CORS 설정을 확인하세요.", {
      kind: "network",
    });
  } finally {
    clearTimeout(timer);
  }
}

export async function apiRequest(path, options = {}) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const accessToken = options.accessToken ?? getApiAccessToken();
  const { accessToken: _accessToken, timeoutMs = DEFAULT_TIMEOUT_MS, ...fetchOptions } = options;
  const method = (fetchOptions.method || "GET").toUpperCase();
  if (!accessToken) {
    throw new ApiError("접속 토큰을 먼저 입력하세요.", { kind: "auth" });
  }

  const url = `${API_BASE_URL}${normalizedPath}`;
  const requestInit = {
    ...fetchOptions,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
      ...(fetchOptions.headers || {}),
    },
  };

  let response;
  try {
    response = await fetchWithTimeout(url, requestInit, timeoutMs);
  } catch (error) {
    // 무료 호스팅 콜드스타트 대응: 조회 요청은 한 번만 재시도한다. (변경 요청은 중복 실행 위험 때문에 재시도하지 않음)
    if (method !== "GET") throw error;
    response = await fetchWithTimeout(url, requestInit, timeoutMs);
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "요청에 실패했습니다." }));
    throw new ApiError(body.detail || "요청에 실패했습니다.", { status: response.status });
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
    snapshot: () => apiRequest("/api/portfolio/snapshot", { method: "POST" }),
    benchmarkReturns: (days = 60) => apiRequest(`/api/portfolio/benchmark-returns?days=${days}`),
  },
  reports: {
    latest: () => apiRequest("/api/reports/latest"),
    list: () => apiRequest("/api/reports"),
    get: (id) => apiRequest(`/api/reports/${id}`),
    generate: (reportType) =>
      apiRequest(`/api/reports/${reportType}/manual-generate`, { method: "POST" }),
    jobStatus: (jobId) => apiRequest(`/api/reports/manual-jobs/${jobId}`),
  },
  performanceLogs: {
    list: () => apiRequest("/api/performance-logs"),
  },
  recommendationCycles: {
    list: () => apiRequest("/api/recommendation-cycles"),
  },
  recommendationStats: {
    get: () => apiRequest("/api/recommendation-stats"),
  },
  notifications: {
    list: (unreadOnly = false, limit = 100) =>
      apiRequest(`/api/notifications?unread_only=${unreadOnly}&limit=${limit}`),
    read: (id) => apiRequest(`/api/notifications/${id}/read`, { method: "POST" }),
    readAll: () => apiRequest("/api/notifications/read-all", { method: "POST" }),
  },
  backtests: {
    runRules: (reportType, limit = 12) =>
      apiRequest(`/api/backtests/rules/run?report_type=${reportType}&limit=${limit}`, {
        method: "POST",
      }),
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
