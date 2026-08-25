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

const assetApi = vi.hoisted(() => ({
  list: vi.fn(),
}));

vi.mock("../api/advisory.js", () => api);
vi.mock("../api/client.js", () => ({ api: { assets: assetApi } }));

import Advisory from "./Advisory.jsx";

describe("Advisory page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    api.listAdvisoryAnalyses.mockResolvedValue([]);
    assetApi.list.mockResolvedValue([
      { id: "asset-aapl", ticker: "AAPL", name: "Apple", market: "US", quantity: 3 },
      { id: "asset-cash", ticker: "KRW", name: "현금", market: "CASH", quantity: 100000 },
      { id: "asset-zero", ticker: "MSFT", name: "Microsoft", market: "US", quantity: 0 },
    ]);
    api.getAdvisoryStatus.mockResolvedValue({
      storage_status: "available",
      ai_narrative_status: "configured",
      migration_file: "backend/app/db/migrations/017_create_advisory_analyses.sql",
      profit_taking_review_status: "available",
      profit_taking_review_migration_file:
        "backend/app/db/migrations/020_add_profit_taking_review_advisory.sql",
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

  it("renders the active job beneath its feature card", async () => {
    api.getAdvisoryJob.mockImplementation(() => new Promise(() => {}));
    render(<Advisory />);

    await waitFor(() => expect(screen.getByRole("button", { name: "AI 자문 요청" })).toBeEnabled());
    fireEvent.change(screen.getByPlaceholderText("예: AAPL, MSFT, NVDA"), {
      target: { value: "aapl" },
    });
    fireEvent.click(screen.getByRole("button", { name: "AI 자문 요청" }));

    const featureCard = screen.getByRole("button", { name: /저평가 미국 주식/ });
    const featureItem = featureCard.closest(".advisory-feature-item");
    expect(featureItem).toContainElement(await screen.findByRole("status"));
    expect(
      screen.getByRole("heading", { name: "최근 자문" }).closest(".advisory-history"),
    ).toBeTruthy();
  });

  it("opens a recent advisory result beneath the matching feature card", async () => {
    api.listAdvisoryAnalyses.mockResolvedValue([
      {
        analysis_id: "analysis-sector-1",
        analysis_type: "sector_outlook",
        created_at: "2026-07-17T00:00:00Z",
      },
    ]);
    api.getAdvisoryAnalysis.mockResolvedValue({
      analysis_id: "analysis-sector-1",
      analysis_type: "sector_outlook",
      result: {
        analysis_type: "sector_outlook",
        summary: "섹터 전망 결과",
        data_quality: { status: "available" },
        disclaimer: "투자 의사결정 지원 정보입니다.",
      },
    });
    render(<Advisory />);

    fireEvent.click(await screen.findByRole("button", { name: /섹터 전망.*2026년/ }));

    const featureCard = screen
      .getAllByRole("button", { name: /섹터 전망/ })
      .find((button) => button.classList.contains("advisory-feature-card"));
    const featureItem = featureCard.closest(".advisory-feature-item");
    expect(featureItem).toContainElement(await screen.findByText("자문 결과"));
    expect(
      screen.getByRole("heading", { name: "최근 자문" }).closest(".advisory-history"),
    ).toBeTruthy();
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

  it("submits the stored-asset profit-taking review without price or quantity inputs", async () => {
    render(<Advisory />);

    await waitFor(() => expect(assetApi.list).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole("button", { name: "AI 자문 요청" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /이익실현 판단/ }));

    const assetSelect = screen.getByLabelText("이익실현을 검토할 보유 자산");
    expect(assetSelect).toHaveTextContent("Apple (AAPL)");
    expect(assetSelect).not.toHaveTextContent("현금");
    expect(assetSelect).not.toHaveTextContent("Microsoft");
    expect(screen.getByDisplayValue("중기")).toBeInTheDocument();
    expect(screen.getByText(/기존 리포트 의견은 비교 정보로만 표시/)).toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();

    fireEvent.change(assetSelect, { target: { value: "asset-aapl" } });
    fireEvent.click(screen.getByRole("button", { name: "AI 자문 요청" }));

    await waitFor(() =>
      expect(api.createAdvisoryJob).toHaveBeenCalledWith({
        analysis_type: "profit_taking_review",
        asset_id: "asset-aapl",
        review_horizon: "medium",
      }),
    );
  });

  it("requires a stored asset before submitting a profit-taking review", async () => {
    render(<Advisory />);

    await waitFor(() => expect(screen.getByRole("button", { name: "AI 자문 요청" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: /이익실현 판단/ }));
    fireEvent.click(screen.getByRole("button", { name: "AI 자문 요청" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/보유 자산을 선택하세요/);
    expect(api.createAdvisoryJob).not.toHaveBeenCalled();
  });

  it("blocks only the profit-taking review when migration 020 is missing", async () => {
    api.getAdvisoryStatus.mockResolvedValue({
      storage_status: "available",
      ai_narrative_status: "configured",
      migration_file: "backend/app/db/migrations/017_create_advisory_analyses.sql",
      profit_taking_review_status: "migration_required",
      profit_taking_review_migration_file:
        "backend/app/db/migrations/020_add_profit_taking_review_advisory.sql",
    });
    render(<Advisory />);

    expect(await screen.findByText(/이익실현 판단을 사용하려면/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /이익실현 판단/ }));

    expect(screen.getByRole("button", { name: "AI 자문 요청" })).toBeDisabled();
    expect(api.createAdvisoryJob).not.toHaveBeenCalled();
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
      analysis_type: "post_earnings_opportunities",
    });
    api.getAdvisoryAnalysis.mockResolvedValue({
      analysis_id: "restored-analysis",
      analysis_type: "post_earnings_opportunities",
      result: {
        analysis_type: "post_earnings_opportunities",
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
    const featureCard = screen.getByRole("button", { name: /실적 발표 후 기회/ });
    expect(featureCard.closest(".advisory-feature-item")).toContainElement(
      screen.getByText("자문 결과"),
    );
  });

  it("renders an inline completed analysis beneath its nested analysis type card", async () => {
    window.sessionStorage.setItem(ACTIVE_ADVISORY_JOB_STORAGE_KEY, "restored-inline-job");
    api.getAdvisoryJob.mockResolvedValue({
      job_id: "restored-inline-job",
      status: "completed",
      analysis: {
        analysis_id: "inline-analysis",
        analysis_type: "post_earnings_opportunities",
        result: {
          analysis_type: "post_earnings_opportunities",
          rows: [{ ticker: "MSFT", investment_score: 76, action: "WATCH" }],
          top_candidates: [],
          data_quality: { status: "available" },
          evidence: [],
          disclaimer: "투자 의사결정 참고 정보입니다.",
        },
      },
    });

    render(<Advisory />);

    await waitFor(() => expect(api.getAdvisoryJob).toHaveBeenCalledWith("restored-inline-job"));
    expect((await screen.findAllByText("MSFT")).length).toBeGreaterThan(0);
    const featureCard = screen.getByRole("button", { name: /실적 발표 후 기회/ });
    expect(featureCard.closest(".advisory-feature-item")).toContainElement(
      screen.getByText("자문 결과"),
    );
    expect(api.getAdvisoryAnalysis).not.toHaveBeenCalled();
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
