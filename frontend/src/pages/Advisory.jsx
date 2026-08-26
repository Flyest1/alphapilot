import { useCallback, useEffect, useRef, useState } from "react";

import {
  createAdvisoryJob,
  getAdvisoryAnalysis,
  getAdvisoryJob,
  getAdvisoryStatus,
  listAdvisoryAnalyses,
} from "../api/advisory.js";
import { api } from "../api/client.js";
import AdvisoryFeatureCards from "../components/advisory/AdvisoryFeatureCards.jsx";
import AdvisoryInputForm from "../components/advisory/AdvisoryInputForm.jsx";
import AdvisoryResult from "../components/advisory/AdvisoryResult.jsx";
import {
  buildAdvisoryPayload,
  getAdvisoryFeature,
  validateAdvisoryPayload,
} from "../components/advisory/advisoryFeatures.js";
import { formatAdvisoryDate } from "../components/advisory/advisoryResultUtils.js";
import {
  clearActiveAdvisoryJobId,
  isTerminalAdvisoryJob,
  persistActiveAdvisoryJobId,
  readActiveAdvisoryJobId,
} from "../utils/advisoryJobs.js";

const POLL_INTERVAL_MS = 5000;
const MIGRATION_FILE = "backend/app/db/migrations/017_create_advisory_analyses.sql";
const PROFIT_TAKING_REVIEW_MIGRATION_FILE =
  "backend/app/db/migrations/020_add_profit_taking_review_advisory.sql";
const HIGH_UPSIDE_SPECULATIVE_STOCKS_MIGRATION_FILE =
  "backend/app/db/migrations/021_add_high_upside_speculative_stocks_advisory.sql";

const JOB_ERROR_MESSAGES = {
  stale_active_job: "이전 자문 작업이 응답 없이 만료되었습니다. 새로 요청해 주세요.",
  internal_error: "자문 분석 중 서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
  unsupported_analysis: "이 자문 유형은 현재 지원되지 않습니다. 다른 분석을 선택해 주세요.",
};

const API_ERROR_MESSAGES = {
  migration_required: "자문 저장소 migration이 적용되지 않았습니다.",
  storage_unavailable: "자문 저장소를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.",
};

function blankForm() {
  return {
    ticker: "",
    tickers: "",
    positions: [{ ticker: "", weight_pct: "" }],
    min_market_cap_usd: "",
    lookback_days: "",
    themes: "",
    min_distribution_yield_percent: "",
    customProxies: [{ sector: "", ticker: "" }],
    asset_id: "",
    review_horizon: "medium",
  };
}

function jobIdentifier(job) {
  return job?.job_id || job?.id;
}

function analysisIdentifier(job) {
  return (
    job?.analysis_id || job?.analysis?.analysis_id || job?.analysis?.id || job?.result?.analysis_id
  );
}

function analysisType(value) {
  return (
    value?.analysis_type ||
    value?.analysis?.analysis_type ||
    value?.result?.analysis_type ||
    value?.content?.analysis_type
  );
}

function isComplete(status) {
  return ["completed", "succeeded", "success"].includes(String(status || "").toLowerCase());
}

function isFailed(status) {
  return ["failed", "cancelled", "canceled"].includes(String(status || "").toLowerCase());
}

function analysisItems(payload) {
  if (Array.isArray(payload)) return payload;
  return payload?.items || payload?.analyses || [];
}

function advisoryErrorMessage(error, fallback = "AI 자문 요청에 실패했습니다.") {
  return (
    JOB_ERROR_MESSAGES[error?.error_code] ||
    JOB_ERROR_MESSAGES[error?.code] ||
    API_ERROR_MESSAGES[error?.code] ||
    error?.message ||
    fallback
  );
}

export default function Advisory() {
  const [selectedType, setSelectedType] = useState("undervalued_us_stocks");
  const [form, setForm] = useState(blankForm);
  const [job, setJob] = useState(() => {
    const jobId = readActiveAdvisoryJobId();
    return jobId ? { job_id: jobId, status: "queued" } : null;
  });
  const [selectedAnalysis, setSelectedAnalysis] = useState(null);
  const [history, setHistory] = useState([]);
  const [assets, setAssets] = useState([]);
  const [isLoadingAssets, setIsLoadingAssets] = useState(true);
  const [assetLoadError, setAssetLoadError] = useState("");
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [error, setError] = useState("");
  const [advisoryStatus, setAdvisoryStatus] = useState(null);
  const [advisoryStatusError, setAdvisoryStatusError] = useState("");
  const [isCreatingJob, setIsCreatingJob] = useState(false);
  const [analysisLoadRequest, setAnalysisLoadRequest] = useState(null);
  const [isLoadingCompletedAnalysis, setIsLoadingCompletedAnalysis] = useState(false);
  const submissionLockRef = useRef(false);
  const latestPollRef = useRef(0);
  const terminalJobIdsRef = useRef(new Set());
  const analysisLoadSequenceRef = useRef(0);

  const feature = getAdvisoryFeature(selectedType);
  const activeJobId = jobIdentifier(job);
  const activeJobType = analysisType(job);
  const selectedAnalysisType = analysisType(selectedAnalysis);
  const hasActiveJob = Boolean(activeJobId && !isComplete(job?.status) && !isFailed(job?.status));
  const isSubmitting = isCreatingJob || hasActiveJob;
  const isAdvisoryStorageAvailable = advisoryStatus?.storage_status === "available";
  const isProfitTakingReviewAvailable = advisoryStatus?.profit_taking_review_status === "available";
  const isHighUpsideSpeculativeStocksAvailable =
    advisoryStatus?.high_upside_speculative_stocks_status === "available";
  const isSelectedFeatureAvailable =
    (selectedType !== "profit_taking_review" || isProfitTakingReviewAvailable) &&
    (selectedType !== "high_upside_speculative_stocks" || isHighUpsideSpeculativeStocksAvailable);

  const requestCompletedAnalysis = useCallback((jobId, analysisId) => {
    if (!jobId || !analysisId) return;
    const requestId = ++analysisLoadSequenceRef.current;
    setAnalysisLoadRequest({ jobId, analysisId, requestId });
  }, []);

  useEffect(() => {
    if (!activeJobId) return;
    if (isTerminalAdvisoryJob(job?.status)) {
      clearActiveAdvisoryJobId(activeJobId);
      return;
    }
    persistActiveAdvisoryJobId(activeJobId);
  }, [activeJobId, job?.status]);

  useEffect(() => {
    let cancelled = false;
    api.assets
      .list()
      .then((rows) => {
        if (cancelled) return;
        setAssets(
          (Array.isArray(rows) ? rows : []).filter(
            (asset) => asset?.market !== "CASH" && Number(asset?.quantity) > 0,
          ),
        );
      })
      .catch(() => {
        if (!cancelled)
          setAssetLoadError("보유 자산을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
      })
      .finally(() => {
        if (!cancelled) setIsLoadingAssets(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    getAdvisoryStatus()
      .then((nextStatus) => {
        if (cancelled) return;
        if (nextStatus?.storage_status) {
          setAdvisoryStatus(nextStatus);
          return;
        }
        setAdvisoryStatusError("자문 운영 상태 응답이 올바르지 않습니다.");
      })
      .catch((requestError) => {
        if (!cancelled) {
          setAdvisoryStatusError(
            advisoryErrorMessage(requestError, "운영 상태 조회에 실패했습니다."),
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    listAdvisoryAnalyses()
      .then((payload) => {
        if (!cancelled) setHistory(analysisItems(payload));
      })
      .catch((requestError) => {
        if (!cancelled)
          setError(advisoryErrorMessage(requestError, "최근 자문을 불러오지 못했습니다."));
      })
      .finally(() => {
        if (!cancelled) setIsLoadingHistory(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!activeJobId || !hasActiveJob) return undefined;
    let cancelled = false;
    let intervalId;
    async function pollJob() {
      const pollId = ++latestPollRef.current;
      try {
        const nextJob = await getAdvisoryJob(activeJobId);
        if (
          cancelled ||
          pollId !== latestPollRef.current ||
          terminalJobIdsRef.current.has(activeJobId)
        ) {
          return;
        }
        if (isComplete(nextJob.status) || isFailed(nextJob.status)) {
          terminalJobIdsRef.current.add(activeJobId);
          clearActiveAdvisoryJobId(activeJobId);
          if (intervalId) window.clearInterval(intervalId);
          const nextJobType = analysisType(nextJob);
          if (nextJobType) setSelectedType(nextJobType);
          setJob(nextJob);
          if (isFailed(nextJob.status)) {
            setError(advisoryErrorMessage(nextJob));
            return;
          }
          const nextAnalysisId = analysisIdentifier(nextJob);
          const inlineAnalysis = nextJob.analysis || nextJob.result;
          if (inlineAnalysis) {
            setSelectedAnalysis({
              ...inlineAnalysis,
              analysis_type: analysisType(inlineAnalysis) || nextJobType,
            });
          } else if (nextAnalysisId) {
            requestCompletedAnalysis(activeJobId, nextAnalysisId);
          } else {
            setError(
              "AI 자문 작업은 완료됐지만 결과 식별자를 확인할 수 없습니다. 같은 요청을 다시 실행해 주세요.",
            );
          }
          try {
            const updatedHistory = await listAdvisoryAnalyses();
            if (!cancelled && pollId === latestPollRef.current) {
              setHistory(analysisItems(updatedHistory));
            }
          } catch {
            // The terminal job state remains authoritative even if history refresh fails.
          }
          return;
        }
        const nextJobType = analysisType(nextJob);
        if (nextJobType) setSelectedType(nextJobType);
        setJob(nextJob);
      } catch (requestError) {
        if (!cancelled && pollId === latestPollRef.current)
          setError(advisoryErrorMessage(requestError));
      }
    }
    pollJob();
    intervalId = window.setInterval(pollJob, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [activeJobId, hasActiveJob, requestCompletedAnalysis]);

  useEffect(() => {
    if (!analysisLoadRequest) return undefined;
    let cancelled = false;
    const { jobId, analysisId, requestId } = analysisLoadRequest;
    setIsLoadingCompletedAnalysis(true);
    getAdvisoryAnalysis(analysisId)
      .then((analysis) => {
        if (
          cancelled ||
          requestId !== analysisLoadSequenceRef.current ||
          !terminalJobIdsRef.current.has(jobId)
        ) {
          return;
        }
        const loadedType = analysisType(analysis);
        if (loadedType) setSelectedType(loadedType);
        setSelectedAnalysis(analysis);
        setAnalysisLoadRequest(null);
        setError("");
      })
      .catch(() => {
        if (cancelled || requestId !== analysisLoadSequenceRef.current) return;
        setError(
          "AI 자문 작업은 완료됐지만 결과를 불러오지 못했습니다. 아래 버튼으로 다시 시도하거나 같은 요청을 다시 실행해 주세요.",
        );
      })
      .finally(() => {
        if (!cancelled && requestId === analysisLoadSequenceRef.current) {
          setIsLoadingCompletedAnalysis(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [analysisLoadRequest]);

  function selectFeature(analysisType) {
    setSelectedType(analysisType);
    setForm(blankForm());
    setError("");
  }

  async function submit(event) {
    event.preventDefault();
    if (submissionLockRef.current) return;
    if (!isAdvisoryStorageAvailable) {
      if (advisoryStatus?.storage_status === "migration_required") {
        setError(`자문 저장소 migration이 필요합니다. ${MIGRATION_FILE}`);
      } else if (advisoryStatus?.storage_status === "unavailable") {
        setError("자문 저장소를 사용할 수 없어 요청을 접수할 수 없습니다.");
      } else {
        setError("자문 운영 상태를 확인할 수 없어 요청을 접수할 수 없습니다.");
      }
      return;
    }
    if (!isSelectedFeatureAvailable) {
      const migrationFile =
        selectedType === "high_upside_speculative_stocks"
          ? HIGH_UPSIDE_SPECULATIVE_STOCKS_MIGRATION_FILE
          : PROFIT_TAKING_REVIEW_MIGRATION_FILE;
      setError(`선택한 자문 저장소 migration이 필요합니다. ${migrationFile}`);
      return;
    }
    const payload = buildAdvisoryPayload(feature, form);
    const validationError = validateAdvisoryPayload(feature, payload, form);
    if (validationError) {
      setError(validationError);
      return;
    }
    setError("");
    setSelectedAnalysis(null);
    analysisLoadSequenceRef.current += 1;
    setAnalysisLoadRequest(null);
    submissionLockRef.current = true;
    setIsCreatingJob(true);
    try {
      const createdJob = await createAdvisoryJob(payload);
      terminalJobIdsRef.current.delete(jobIdentifier(createdJob));
      setJob({ ...createdJob, analysis_type: analysisType(createdJob) || feature.id });
    } catch (requestError) {
      setError(advisoryErrorMessage(requestError));
    } finally {
      submissionLockRef.current = false;
      setIsCreatingJob(false);
    }
  }

  async function selectAnalysis(analysis) {
    const analysisId = analysis.id || analysis.analysis_id;
    const nextType = analysisType(analysis);
    if (nextType) setSelectedType(nextType);
    if (!analysisId || analysis.result || analysis.content) {
      setSelectedAnalysis(analysis);
      return;
    }
    setError("");
    try {
      const loadedAnalysis = await getAdvisoryAnalysis(analysisId);
      const loadedType = analysisType(loadedAnalysis);
      if (loadedType) setSelectedType(loadedType);
      setSelectedAnalysis(loadedAnalysis);
    } catch (requestError) {
      setError(advisoryErrorMessage(requestError, "저장된 자문을 불러오지 못했습니다."));
    }
  }

  return (
    <section className="page advisory-page">
      <header className="page-header">
        <div>
          <h1>AI 자문</h1>
          <p>
            시장·공시·ETF 데이터를 바탕으로 검토 자료를 만듭니다. 주문이나 자동매매는 실행하지
            않습니다.
          </p>
        </div>
      </header>
      {advisoryStatusError && (
        <div className="notice" role="alert">
          <span className="alert">자문 운영 상태를 확인하지 못했습니다. {advisoryStatusError}</span>
        </div>
      )}
      {advisoryStatus?.storage_status === "migration_required" && (
        <div className="notice" role="alert">
          <span className="alert">
            자문 기능을 사용하려면 운영 데이터베이스에 migration을 적용해야 합니다. 적용 파일:{" "}
            <code>{advisoryStatus.migration_file || MIGRATION_FILE}</code>
          </span>
        </div>
      )}
      {advisoryStatus?.storage_status === "unavailable" && (
        <div className="notice" role="alert">
          <span className="alert">
            자문 저장소를 사용할 수 없어 결과를 저장하거나 조회할 수 없습니다.
          </span>
        </div>
      )}
      {advisoryStatus?.storage_status === "available" &&
        advisoryStatus?.profit_taking_review_status === "migration_required" && (
          <div className="notice" role="alert">
            <span className="alert">
              이익실현 판단을 사용하려면 운영 데이터베이스에 migration을 적용해야 합니다. 적용 파일:{" "}
              <code>
                {advisoryStatus.profit_taking_review_migration_file ||
                  PROFIT_TAKING_REVIEW_MIGRATION_FILE}
              </code>
            </span>
          </div>
        )}
      {advisoryStatus?.storage_status === "available" &&
        advisoryStatus?.high_upside_speculative_stocks_status === "migration_required" && (
          <div className="notice" role="alert">
            <span className="alert">
              고위험·고상승 잠재 종목 탐색을 사용하려면 운영 데이터베이스에 migration을 적용해야
              합니다. 적용 파일:{" "}
              <code>
                {advisoryStatus.high_upside_speculative_stocks_migration_file ||
                  HIGH_UPSIDE_SPECULATIVE_STOCKS_MIGRATION_FILE}
              </code>
            </span>
          </div>
        )}
      {advisoryStatus?.ai_narrative_status === "not_configured" && (
        <div className="notice" role="status">
          <span className="alert">
            OpenAI 자문 설명이 설정되지 않았습니다. 요청은 결정론적 분석만 제공하며 AI 설명은
            생성되지 않습니다.
          </span>
        </div>
      )}
      {error && (
        <div className="notice advisory-retry-notice" role="alert">
          <span className="alert">{error}</span>
          {analysisLoadRequest && (
            <button
              className="secondary-action compact-action"
              disabled={isLoadingCompletedAnalysis}
              type="button"
              onClick={() =>
                requestCompletedAnalysis(analysisLoadRequest.jobId, analysisLoadRequest.analysisId)
              }
            >
              {isLoadingCompletedAnalysis ? "완료 결과 불러오는 중" : "완료 결과 다시 불러오기"}
            </button>
          )}
        </div>
      )}
      <AdvisoryFeatureCards selectedType={selectedType} onSelect={selectFeature}>
        {(selectedFeature) => {
          const isActiveFeatureJob = hasActiveJob && activeJobType === selectedFeature.id;
          const isLoadingFeatureResult =
            isLoadingCompletedAnalysis && activeJobType === selectedFeature.id;
          const isSelectedFeatureAnalysis = selectedAnalysisType === selectedFeature.id;

          return (
            <div className="advisory-feature-current">
              <fieldset
                className="advisory-feature-inline-form"
                disabled={!isAdvisoryStorageAvailable}
                style={{ border: 0, margin: 0, minInlineSize: 0, padding: 0 }}
              >
                <AdvisoryInputForm
                  assets={assets}
                  assetLoadError={assetLoadError}
                  feature={selectedFeature}
                  form={form}
                  isDisabled={
                    (selectedFeature.id === "profit_taking_review" &&
                      !isProfitTakingReviewAvailable) ||
                    (selectedFeature.id === "high_upside_speculative_stocks" &&
                      !isHighUpsideSpeculativeStocksAvailable)
                  }
                  isLoadingAssets={isLoadingAssets}
                  isSubmitting={isSubmitting}
                  onChange={setForm}
                  onSubmit={submit}
                />
              </fieldset>
              {isActiveFeatureJob && (
                <p className="notice advisory-inline-job-status" role="status">
                  {job?.status === "queued"
                    ? "AI 자문 요청이 대기 중입니다."
                    : "AI 자문을 분석 중입니다."}{" "}
                  이 화면을 유지하면 결과를 자동으로 불러옵니다.
                </p>
              )}
              {isLoadingFeatureResult && (
                <p className="notice advisory-inline-job-status" role="status">
                  AI 자문 결과를 불러오는 중입니다.
                </p>
              )}
              {isSelectedFeatureAnalysis && <AdvisoryResult analysis={selectedAnalysis} />}
            </div>
          );
        }}
      </AdvisoryFeatureCards>
      <section className="panel advisory-history">
        <div className="section-heading">
          <div>
            <h2>최근 자문</h2>
            <p>이전 분석을 선택해 결과를 다시 확인할 수 있습니다.</p>
          </div>
        </div>
        {isLoadingHistory ? (
          <p className="field-hint">최근 자문을 불러오는 중입니다.</p>
        ) : !history.length ? (
          <p className="empty-state">아직 저장된 AI 자문 결과가 없습니다.</p>
        ) : (
          <div className="advisory-history-list">
            {history.map((analysis) => (
              <button
                className={selectedAnalysis?.analysis_id === analysis.analysis_id ? "active" : ""}
                key={analysis.id || analysis.analysis_id}
                type="button"
                onClick={() => selectAnalysis(analysis)}
              >
                <strong>{getAdvisoryFeature(analysis.analysis_type).title}</strong>
                <span>
                  {analysis.created_at || analysis.generated_at
                    ? formatAdvisoryDate(analysis.created_at || analysis.generated_at)
                    : "기준시각 제공되지 않음"}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}
