import { apiRequest } from "./client.js";

const JOBS_PATH = "/api/advisory/jobs";
const ANALYSES_PATH = "/api/advisory/analyses";
const STATUS_PATH = "/api/advisory/status";

export function getAdvisoryStatus() {
  return apiRequest(STATUS_PATH);
}

export function createAdvisoryJob(payload) {
  return apiRequest(JOBS_PATH, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getAdvisoryJob(jobId) {
  return apiRequest(`${JOBS_PATH}/${jobId}`);
}

export function getAdvisoryAnalysis(analysisId) {
  return apiRequest(`${ANALYSES_PATH}/${analysisId}`);
}

export function listAdvisoryAnalyses() {
  return apiRequest(ANALYSES_PATH);
}
