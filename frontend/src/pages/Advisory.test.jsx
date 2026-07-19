import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ACTIVE_ADVISORY_JOB_STORAGE_KEY } from "../utils/advisoryJobs.js";

const api = vi.hoisted(() => ({
  createAdvisoryJob: vi.fn(),
  getAdvisoryAnalysis: vi.fn(),
  getAdvisoryJob: vi.fn(),
  getAdvisoryStatus: vi.fn(),
  listAdvisoryAnalyses: vi.fn(),
}));

vi.mock("../api/advisory.js", () => api);

import Advisory from "./Advisory.jsx";

describe("Advisory page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    api.listAdvisoryAnalyses.mockResolvedValue([]);
    api.getAdvisoryStatus.mockResolvedValue({
      storage_status: "available",
      ai_narrative_status: "configured",
      migration_file: "backend/app/db/migrations/017_create_advisory_analyses.sql",
    });
    api.createAdvisoryJob.mockResolvedValue({
      job_id: "job-1",
      status: "queued",
      analysis_type: "undervalued_us_stocks",
    });
    api.getAdvisoryJob.mockResolvedValue({
      job_id: "job-1",
      status: "completed",
      analysis_id: "analysis-1",
      analysis_type: "undervalued_us_stocks",
    });
    api.getAdvisoryAnalysis.mockResolvedValue({
      analysis_id: "analysis-1",
      analysis_type: "undervalued_us_stocks",
      result: {
        rows: [{ ticker: "AAPL", action: "WATCH" }],
        data_quality: { status: "partial", providers: ["yfinance"] },
        disclaimer: "투자 의사결정 지원 정보입니다.",
      },
    });
  });

  it("submits a manual request, polls the job, and renders the saved result", async () => {
    render(<Advisory />);

    await waitFor(() => expect(api.listAdvisoryAnalyses).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole("button", { name: "AI 자문 요청" })).toBeEnabled());
    fireEvent.change(screen.getByPlaceholderText("예: AAPL, MSFT, NVDA"), {
      target: { value: "aapl" },
    });
    fireEvent.click(screen.getByRole("button", { name: "AI 자문 요청" }));

    await waitFor(() =>
      expect(api.createAdvisoryJob).toHaveBeenCalledWith({
        analysis_type: "undervalued_us_stocks",
        tickers: ["AAPL"],
        max_results: 5,
      }),
    );
    await waitFor(() => expect(api.getAdvisoryJob).toHaveBeenCalledWith("job-1"));
    await waitFor(() => expect(api.getAdvisoryAnalysis).toHaveBeenCalledWith("analysis-1"));
    expect(await screen.findByText("자문 결과")).toBeInTheDocument();
    expect(screen.getAllByText("AAPL")).not.toHaveLength(0);
    expect(screen.getAllByText("관찰")).not.toHaveLength(0);
  });

  it("opens the selected card's form inline and submits supplied advanced inputs", async () => {
    render(<Advisory />);

    await waitFor(() => expect(screen.getByRole("button", { name: "AI 자문 요청" })).toBeEnabled());
    const earningsCard = screen.getByRole("button", { name: /실적 발표 후 기회/ });
    fireEvent.click(earningsCard);

    const inlineForm = screen.getByRole("button", { name: "AI 자문 요청" }).closest("fieldset");
    expect(inlineForm).toHaveClass("advisory-feature-inline-form");
    expect(earningsCard.parentElement).toContainElement(inlineForm);

    fireEvent.change(screen.getByPlaceholderText("예: AAPL, MSFT, NVDA"), {
      target: { value: "msft" },
    });
    fireEvent.change(screen.getByLabelText("실적 발표 조회 기간 (일, 선택)"), {
      target: { value: "30" },
    });
    fireEvent.click(screen.getByRole("button", { name: "AI 자문 요청" }));

    await waitFor(() =>
      expect(api.createAdvisoryJob).toHaveBeenCalledWith({
        analysis_type: "post_earnings_opportunities",
        tickers: ["MSFT"],
        max_results: 5,
        lookback_days: 30,
      }),
    );
  });

  it("shows the required migration and blocks a new request", async () => {
    api.getAdvisoryStatus.mockResolvedValue({
      storage_status: "migration_required",
      ai_narrative_status: "configured",
      migration_file: "backend/app/db/migrations/017_create_advisory_analyses.sql",
    });
    render(<Advisory />);

    expect(
      await screen.findByText(/운영 데이터베이스에 migration을 적용해야 합니다/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "AI 자문 요청" }));

    await waitFor(() => expect(api.createAdvisoryJob).not.toHaveBeenCalled());
    expect(screen.getAllByText(/017_create_advisory_analyses\.sql/)).not.toHaveLength(0);
  });

  it.each([
    ["returns no status", () => api.getAdvisoryStatus.mockResolvedValue(null)],
    [
      "fails to load status",
      () => api.getAdvisoryStatus.mockRejectedValue(new Error("status failed")),
    ],
  ])("fails closed when the advisory status %s", async (_scenario, setStatusResponse) => {
    setStatusResponse();
    render(<Advisory />);

    const submitButton = screen.getByRole("button", { name: "AI 자문 요청" });
    await waitFor(() => expect(submitButton).toBeDisabled());
    expect(api.createAdvisoryJob).not.toHaveBeenCalled();
  });

  it("prevents duplicate submissions while the create request is pending", async () => {
    let resolveCreate;
    api.createAdvisoryJob.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveCreate = resolve;
        }),
    );
    render(<Advisory />);

    const submitButton = screen.getByRole("button", { name: "AI 자문 요청" });
    await waitFor(() => expect(submitButton).toBeEnabled());
    fireEvent.change(screen.getByPlaceholderText("예: AAPL, MSFT, NVDA"), {
      target: { value: "aapl" },
    });

    fireEvent.click(submitButton);
    fireEvent.click(submitButton);

    expect(api.createAdvisoryJob).toHaveBeenCalledTimes(1);
    resolveCreate({ job_id: "job-1", status: "queued" });
    await waitFor(() => expect(api.getAdvisoryJob).toHaveBeenCalledWith("job-1"));
  });

  it("shows when OpenAI narrative generation is not configured", async () => {
    api.getAdvisoryStatus.mockResolvedValue({
      storage_status: "available",
      ai_narrative_status: "not_configured",
    });
    render(<Advisory />);

    expect(await screen.findByText(/OpenAI 자문 설명이 설정되지 않았습니다/)).toBeInTheDocument();
  });

  it("formats advisory history timestamps in Korean Asia/Seoul time", async () => {
    api.listAdvisoryAnalyses.mockResolvedValue([
      {
        analysis_id: "analysis-history-1",
        analysis_type: "undervalued_us_stocks",
        created_at: "2026-07-16T15:30:00Z",
      },
    ]);

    render(<Advisory />);

    expect(await screen.findByText(/2026년 7월 17일/)).toBeInTheDocument();
  });

  it("restores an active job after refresh and clears only its terminal job id", async () => {
    window.sessionStorage.setItem(ACTIVE_ADVISORY_JOB_STORAGE_KEY, "restored-job");
    api.getAdvisoryJob.mockResolvedValue({
      job_id: "restored-job",
      status: "completed",
      analysis_id: "restored-analysis",
      analysis_type: "undervalued_us_stocks",
    });
    api.getAdvisoryAnalysis.mockResolvedValue({
      analysis_id: "restored-analysis",
      analysis_type: "undervalued_us_stocks",
      result: {
        analysis_type: "undervalued_us_stocks",
        rows: [{ ticker: "AAPL", investment_score: 82, action: "WATCH" }],
        top_candidates: [],
        data_quality: { status: "available" },
        evidence: [],
        disclaimer: "투자 의사결정 참고 정보입니다.",
      },
    });

    render(<Advisory />);

    await waitFor(() => expect(api.getAdvisoryJob).toHaveBeenCalledWith("restored-job"));
    await waitFor(() => expect(api.getAdvisoryAnalysis).toHaveBeenCalledWith("restored-analysis"));
    expect(window.sessionStorage.getItem(ACTIVE_ADVISORY_JOB_STORAGE_KEY)).toBeNull();
    expect((await screen.findAllByText("AAPL")).length).toBeGreaterThan(0);
  });

  it("stops polling at completed status and offers retry when analysis loading fails", async () => {
    api.getAdvisoryAnalysis
      .mockRejectedValueOnce(new Error("analysis unavailable"))
      .mockResolvedValueOnce({
        analysis_id: "analysis-1",
        analysis_type: "undervalued_us_stocks",
        result: {
          analysis_type: "undervalued_us_stocks",
          rows: [{ ticker: "AAPL", investment_score: 82, action: "WATCH" }],
          top_candidates: [],
          data_quality: { status: "available" },
          evidence: [],
          disclaimer: "투자 의사결정 참고 정보입니다.",
        },
      });

    render(<Advisory />);

    await waitFor(() => expect(screen.getByRole("button", { name: "AI 자문 요청" })).toBeEnabled());
    fireEvent.change(screen.getByPlaceholderText("예: AAPL, MSFT, NVDA"), {
      target: { value: "aapl" },
    });
    fireEvent.click(screen.getByRole("button", { name: "AI 자문 요청" }));

    expect(
      await screen.findByText(/작업은 완료됐지만 결과를 불러오지 못했습니다/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/AI 자문을 분석 중입니다/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "AI 자문 요청" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "완료 결과 다시 불러오기" })).toBeEnabled();
    expect(window.sessionStorage.getItem(ACTIVE_ADVISORY_JOB_STORAGE_KEY)).toBeNull();
    expect(api.getAdvisoryJob).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "완료 결과 다시 불러오기" }));

    expect((await screen.findAllByText("AAPL")).length).toBeGreaterThan(0);
    expect(api.getAdvisoryAnalysis).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["stale_active_job", "이전 자문 작업이 응답 없이 만료되었습니다. 새로 요청해 주세요."],
    ["internal_error", "자문 분석 중 서버 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."],
    ["unsupported_analysis", "이 자문 유형은 현재 지원되지 않습니다. 다른 분석을 선택해 주세요."],
  ])("maps failed job error code %s to Korean guidance", async (errorCode, message) => {
    api.createAdvisoryJob.mockResolvedValue({
      job_id: "job-1",
      status: "queued",
      analysis_type: "undervalued_us_stocks",
    });
    api.getAdvisoryJob.mockResolvedValue({
      job_id: "job-1",
      status: "failed",
      error_code: errorCode,
      analysis_type: "undervalued_us_stocks",
    });
    render(<Advisory />);

    await waitFor(() => expect(screen.getByRole("button", { name: "AI 자문 요청" })).toBeEnabled());
    fireEvent.change(screen.getByPlaceholderText("예: AAPL, MSFT, NVDA"), {
      target: { value: "aapl" },
    });
    fireEvent.click(screen.getByRole("button", { name: "AI 자문 요청" }));

    expect(await screen.findByText(message)).toBeInTheDocument();
  });
});
