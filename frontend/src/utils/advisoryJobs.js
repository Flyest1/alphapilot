export const ACTIVE_ADVISORY_JOB_STORAGE_KEY = "alphapilot.activeAdvisoryJobId";

export function isTerminalAdvisoryJob(status) {
  return ["completed", "succeeded", "success", "failed", "cancelled", "canceled"].includes(
    String(status || "").toLowerCase(),
  );
}

export function readActiveAdvisoryJobId() {
  try {
    return window.sessionStorage.getItem(ACTIVE_ADVISORY_JOB_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

export function persistActiveAdvisoryJobId(jobId) {
  if (!jobId) return;
  try {
    window.sessionStorage.setItem(ACTIVE_ADVISORY_JOB_STORAGE_KEY, String(jobId));
  } catch {
    // Session storage can be unavailable in private browsing contexts.
  }
}

export function clearActiveAdvisoryJobId(jobId) {
  try {
    const storedJobId = window.sessionStorage.getItem(ACTIVE_ADVISORY_JOB_STORAGE_KEY);
    if (!jobId || storedJobId === String(jobId)) {
      window.sessionStorage.removeItem(ACTIVE_ADVISORY_JOB_STORAGE_KEY);
    }
  } catch {
    // The running job remains usable even if session storage is unavailable.
  }
}
