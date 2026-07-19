import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AdvisoryResult from "./AdvisoryResult.jsx";
import { formatAdvisoryDate } from "./advisoryResultUtils.js";

const base = {
  data_quality: { status: "available", provider: "yfinance", source_as_of: "2026-07-16" },
  evidence: [
    {
      evidence_id: "E1",
      title: "원천 근거",
      provider: "yfinance",
      source_as_of: "2026-07-16",
      url: "https://example.com/evidence",
    },
  ],
  disclaimer: "투자 의사결정 참고 정보입니다.",
};

const fixtures = [
  [
    "undervalued_us_stocks",
    "미국 저평가 후보",
    {
      rows: [
        {
          ticker: "AAPL",
          investment_score: 82,
          three_month_return_pct: -8,
          action: "BUY",
          analysis_status: "available",
        },
      ],
      top_candidates: [
        { ticker: "AAPL", investment_score: 82, action: "BUY", analysis_status: "available" },
      ],
    },
  ],
  [
    "etf_rebalancing",
    "ETF 리밸런싱 참고",
    {
      etfs: [
        {
          ticker: "VOO",
          current_weight_pct: 60,
          target_weight_pct: 55,
          analysis_status: "available",
        },
      ],
      top10_overlap: [
        { ticker_a: "VOO", ticker_b: "QQQ", minimum_confirmed_top10_overlap_pct: 24 },
      ],
      scenarios: [{ name: "균형", status: "caution" }],
    },
  ],
  [
    "post_earnings_opportunities",
    "실적 발표 후 관찰 후보",
    {
      rows: [
        {
          ticker: "MSFT",
          opportunity_score: 73,
          post_earnings_return_pct: -6,
          action: "WATCH",
          analysis_status: "available",
        },
      ],
      rankings: [
        { ticker: "MSFT", opportunity_score: 73, action: "WATCH", analysis_status: "available" },
      ],
    },
  ],
  [
    "ai_beneficiaries",
    "AI 수혜 근거 점검",
    {
      rows: [
        {
          ticker: "NVDA",
          classification: "verified_ai_beneficiary",
          investment_appeal_10: 8.2,
          analysis_status: "available",
        },
      ],
      verified_ai_beneficiaries: [
        {
          ticker: "NVDA",
          investment_appeal_10: 8.2,
          classification: "verified_ai_beneficiary",
          analysis_status: "available",
        },
      ],
      ai_theme_caution: [],
    },
  ],
  [
    "high_dividend_etfs",
    "고배당 ETF 비교",
    {
      etfs: [{ ticker: "SCHD", distribution_yield_pct: 3.6, analysis_status: "available" }],
      caution_etfs: [],
      relatively_stable_etfs: [
        { ticker: "SCHD", distribution_yield_pct: 3.6, analysis_status: "available" },
      ],
      beginner_explanation: "분배금과 총수익률을 함께 확인합니다.",
    },
  ],
  [
    "sec_filing_risk",
    "SEC 공시 위험 점검",
    {
      ticker: "AAPL",
      risk_rating: "caution",
      evaluation_status: "available",
      rating_reason: "공시 문구 변화를 확인했습니다.",
      latest_filings: [
        {
          form: "10-Q",
          accession_number: "0000320193-26-000001",
          filed_at: "2026-07-15",
          url: "https://www.sec.gov/Archives/edgar/data/320193/example.txt",
        },
      ],
      risk_categories: [{ category: "수요", severity: "caution", severity_score: 7 }],
      management_caution_signals: [],
      newly_emphasized_risks: [],
      key_sentences: [],
    },
  ],
  [
    "etf_overlap",
    "ETF 중복·분산 점검",
    {
      etfs: [{ ticker: "VOO" }],
      pairwise_overlap: [{ ticker_a: "VOO", ticker_b: "QQQ", overlap_pct: 42 }],
      actual_company_exposure: [{ ticker: "AAPL", company_weight_pct: 8.1 }],
      style_exposure_approximation: {},
      requested_exposure_summary: {},
      diversification_assessment: {},
      rebalancing_plans: [{ name: "분산 참고", status: "caution" }],
      target_weight_scenarios: [],
    },
  ],
  [
    "sector_outlook",
    "섹터 전망 참고",
    {
      proxy_universe: { technology: "XLK" },
      sectors: [
        {
          sector: "기술",
          proxy_ticker: "XLK",
          outlook_score: 72,
          return_3m_pct: 8,
          analysis_status: "available",
        },
      ],
      investor_portfolios: [{ name: "균형", profile: "balanced", status: "available" }],
      market_input_coverage: {},
    },
  ],
];

describe("AdvisoryResult", () => {
  it.each(fixtures)("renders the %s dedicated result view", (analysisType, title, result) => {
    render(
      <AdvisoryResult analysis={{ result: { ...base, analysis_type: analysisType, ...result } }} />,
    );

    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    expect(screen.getByText("원천 근거")).toBeInTheDocument();
  });

  it("uses decision-support labels instead of order-like actions", () => {
    render(
      <AdvisoryResult
        analysis={{
          result: {
            ...base,
            analysis_type: "undervalued_us_stocks",
            rows: [{ ticker: "AAPL", action: "BUY" }],
            top_candidates: [],
          },
        }}
      />,
    );

    expect(screen.getAllByText("진입 후보")).not.toHaveLength(0);
    expect(screen.queryByText("BUY")).not.toBeInTheDocument();
  });

  it("shows data limitations before SEC details and exposes only official Archives links", () => {
    render(
      <AdvisoryResult
        analysis={{
          result: {
            ...base,
            analysis_type: "sec_filing_risk",
            data_quality: { status: "data-limited" },
            latest_filings: [
              {
                form: "10-K",
                accession_number: "0001",
                filed_at: "2026-07-10",
                url: "https://www.sec.gov/Archives/edgar/data/1/file.txt",
              },
              {
                form: "8-K",
                accession_number: "0002",
                filed_at: "2026-07-11",
                url: "https://example.com/not-sec",
              },
            ],
            newly_emphasized_risks: [],
            risk_categories: [],
            management_caution_signals: [],
            key_sentences: [],
            risk_rating: "caution",
            evaluation_status: "data-limited",
            rating_reason: "자료 제한",
          },
        }}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("데이터 제한 안내");
    expect(screen.getByRole("link", { name: "SEC Archives 원문" })).toHaveAttribute(
      "href",
      "https://www.sec.gov/Archives/edgar/data/1/file.txt",
    );
    expect(screen.getAllByText("접수 번호")).toHaveLength(2);
  });

  it("labels N-PORT evidence as delayed filing data rather than current flow", () => {
    render(
      <AdvisoryResult
        analysis={{
          result: {
            ...base,
            analysis_type: "high_dividend_etfs",
            etfs: [
              {
                ticker: "FUND",
                provider: "sec_n-port",
                form: "N-PORT-P",
                filing_period: "2026-03-31",
                disclosure_delay_days: 60,
              },
            ],
            caution_etfs: [],
            relatively_stable_etfs: [],
            beginner_explanation: "",
          },
        }}
      />,
    );

    expect(screen.getByRole("note")).toHaveTextContent(
      "현재 또는 일별 ETF 흐름으로 해석하지 마세요.",
    );
  });

  it("detects delayed N-PORT context nested in sector results", () => {
    render(
      <AdvisoryResult
        analysis={{
          result: {
            ...base,
            analysis_type: "sector_outlook",
            sectors: [
              {
                sector: "기술",
                proxy_ticker: "XLK",
                etf_flow_context: {
                  provider: "sec_edgar_nport",
                  status: "available",
                  series_id: "S-XLK",
                  public_data_delay_days: 60,
                  flow_fields: { sales: 10, redemption: 8 },
                  filings: [{ report_date: "2026-03-31" }, { report_date: "2026-04-30" }],
                  limitations: [
                    "SEC N-PORT public data is delayed and is not current daily ETF flow data.",
                  ],
                },
              },
            ],
            investor_portfolios: [],
          },
        }}
      />,
    );

    expect(screen.getByRole("note")).toHaveTextContent("2026년 4월 30일");
    expect(screen.getByRole("note")).toHaveTextContent("60일 지연");
    expect(screen.getByRole("note")).toHaveTextContent(
      "현재 또는 일별 ETF 흐름으로 해석하지 마세요.",
    );
  });

  it.each([
    ["partial", "일부 지표가 제한되어 제한사항을 함께 확인하세요."],
    ["limited", "사용 가능한 데이터 범위가 제한되어 일부 결과만 참고할 수 있습니다."],
  ])("shows a priority warning for %s data", (status, message) => {
    render(
      <AdvisoryResult
        analysis={{
          result: {
            ...base,
            analysis_type: "sector_outlook",
            data_quality: { status },
            sectors: [],
            investor_portfolios: [],
          },
        }}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(message);
  });

  it("uses the root partial status instead of escalating a limited child row", () => {
    render(
      <AdvisoryResult
        analysis={{
          result: {
            ...base,
            data_quality: { status: "partial" },
            rows: [{ ticker: "AAPL", analysis_status: "data-limited" }],
          },
        }}
      />,
    );

    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0]).toHaveTextContent("일부 지표가 제한되어 제한사항을 함께 확인하세요.");
  });

  it("renders only allowlisted HTTPS evidence links", () => {
    const evidence = [
      {
        evidence_id: "SEC1",
        title: "SEC evidence",
        provider: "sec_edgar",
        url: "https://data.sec.gov/submissions/CIK0000320193.json",
      },
      {
        evidence_id: "FRED1",
        title: "FRED evidence",
        provider: "fred",
        url: "https://fred.stlouisfed.org/series/CPIAUCSL",
      },
      {
        evidence_id: "YF1",
        title: "Yahoo evidence",
        provider: "yfinance",
        url: "https://finance.yahoo.com/quote/AAPL",
      },
      {
        evidence_id: "GDELT1",
        provider: "gdelt",
        url: "https://api.gdeltproject.org/api/v2/doc/doc",
      },
      {
        evidence_id: "BAD1",
        title: "Unknown provider",
        provider: "unknown",
        url: "https://www.sec.gov/Archives/example.txt",
      },
      {
        evidence_id: "BAD2",
        title: "Wrong host",
        provider: "sec_edgar",
        source_as_of: "2026-07-15",
        url: "https://example.com/Archives/example.txt",
      },
      {
        evidence_id: "BAD3",
        title: "Insecure FRED",
        provider: "fred",
        url: "http://fred.stlouisfed.org/series/CPIAUCSL",
      },
    ];

    render(
      <AdvisoryResult
        analysis={{
          result: {
            ...base,
            analysis_type: "sector_outlook",
            evidence,
            sectors: [],
            investor_portfolios: [],
          },
        }}
      />,
    );

    const links = screen.getAllByRole("link", { name: "원문 열기" });
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "https://data.sec.gov/submissions/CIK0000320193.json",
      "https://fred.stlouisfed.org/series/CPIAUCSL",
      "https://finance.yahoo.com/quote/AAPL",
      "https://api.gdeltproject.org/api/v2/doc/doc",
    ]);
    expect(screen.getByText("GDELT1")).toBeInTheDocument();
    expect(
      screen.getAllByText("제공처와 HTTPS 주소를 검증할 수 없어 링크를 표시하지 않습니다."),
    ).toHaveLength(3);
    const rejectedEvidence = screen.getByText("Wrong host").closest("article");
    expect(within(rejectedEvidence).getByText("BAD2")).toBeInTheDocument();
    expect(within(rejectedEvidence).getByText("sec_edgar")).toBeInTheDocument();
    expect(within(rejectedEvidence).getByText("2026년 7월 15일")).toBeInTheDocument();
    expect(within(rejectedEvidence).queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders the structured AI narrative without inline evidence ids", () => {
    render(
      <AdvisoryResult
        analysis={{
          result: {
            ...base,
            analysis_type: "sector_outlook",
            sectors: [],
            investor_portfolios: [],
            ai_narrative: {
              summary: "근거에 기반한 섹터 환경 요약입니다.",
              summary_evidence_ids: ["sector:XLK"],
              key_findings: [
                {
                  text: "기술 섹터의 상대 흐름을 확인했습니다.",
                  point_type: "fact",
                  evidence_ids: ["sector:XLK"],
                },
              ],
              key_risks: [
                {
                  text: "시장 입력의 공백을 함께 고려해야 합니다.",
                  point_type: "limitation",
                  evidence_ids: ["coverage:1"],
                },
              ],
              actions_to_consider: [
                {
                  text: "후속 데이터 갱신 여부를 관찰합니다.",
                  point_type: "inference",
                  evidence_ids: ["coverage:1"],
                },
              ],
              limitations: ["일부 거시 입력이 제한됐습니다."],
              disclaimer: "투자 의사결정 지원 정보입니다.",
            },
          },
        }}
      />,
    );

    expect(screen.getByRole("heading", { name: "AI 설명" })).toBeInTheDocument();
    expect(screen.getByText("근거에 기반한 섹터 환경 요약입니다.")).toBeInTheDocument();
    expect(screen.getByText("기술 섹터의 상대 흐름을 확인했습니다.")).toBeInTheDocument();
    expect(screen.getByText("시장 입력의 공백을 함께 고려해야 합니다.")).toBeInTheDocument();
    expect(screen.getByText("후속 데이터 갱신 여부를 관찰합니다.")).toBeInTheDocument();
    expect(screen.queryByText("sector:XLK")).not.toBeInTheDocument();
    expect(screen.queryByText("coverage:1")).not.toBeInTheDocument();
  });

  it("shows the summary and key findings before supporting metadata", () => {
    render(
      <AdvisoryResult
        analysis={{
          generated_at: "2026-07-16T15:30:00Z",
          result: {
            ...base,
            analysis_type: "undervalued_us_stocks",
            summary: "핵심 요약입니다.",
            top_candidates: [{ ticker: "AAPL", investment_score: 82, action: "WATCH" }],
            rows: [],
            ai_narrative: {
              summary: "핵심 판단 근거입니다.",
              key_findings: [{ text: "가장 중요한 결과입니다." }],
            },
          },
        }}
      />,
    );

    const summary = screen.getByText("핵심 요약입니다.");
    const keyFinding = screen.getByText("가장 중요한 결과입니다.");
    const supportingDetails = screen.getByText("추가 메타데이터 및 근거").closest("details");

    expect(supportingDetails).toBeInTheDocument();
    expect(
      summary.compareDocumentPosition(supportingDetails) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(
      keyFinding.compareDocumentPosition(supportingDetails) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("formats ISO dates with Korean labels in the Asia/Seoul timezone", () => {
    expect(formatAdvisoryDate("2026-07-16")).toBe("2026년 7월 16일");
    expect(formatAdvisoryDate("2026-07-16T15:30:00Z")).toMatch(/2026년 7월 17일/);

    render(
      <AdvisoryResult
        analysis={{
          generated_at: "2026-07-16T15:30:00Z",
          result: {
            ...base,
            analysis_type: "sector_outlook",
            sectors: [],
            investor_portfolios: [],
          },
        }}
      />,
    );

    expect(screen.getAllByText("2026년 7월 16일")).not.toHaveLength(0);
    expect(screen.getByText(/2026년 7월 17일/)).toBeInTheDocument();
  });

  it("keeps data-limited warnings ahead of the structured AI narrative", () => {
    render(
      <AdvisoryResult
        analysis={{
          result: {
            ...base,
            analysis_type: "sector_outlook",
            data_quality: { status: "insufficient_data" },
            sectors: [],
            investor_portfolios: [],
            ai_narrative: {
              summary: "제한된 근거를 요약합니다.",
              key_findings: [],
              key_risks: [],
              actions_to_consider: [],
              limitations: [],
            },
          },
        }}
      />,
    );

    const warning = screen.getByRole("alert");
    const narrativeHeading = screen.getByRole("heading", { name: "AI 설명" });
    expect(
      warning.compareDocumentPosition(narrativeHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("keeps malformed and unknown values renderable", () => {
    render(
      <AdvisoryResult
        analysis={{
          result: {
            analysis_type: "sector_outlook",
            data_quality: null,
            sectors: [null, { sector: "기술", unknown_metric: { unexpected: [null, true] } }],
            investor_portfolios: "invalid",
            evidence: [null, "unknown"],
            disclaimer: null,
            unknown_scalar: "kept",
            future_rows: [{ future_metric: "future-value", nested: { state: "nested-value" } }],
            future_context: {
              nested_state: "watch",
              nested_array: ["alpha", "beta"],
            },
          },
        }}
      />,
    );

    expect(screen.getByText("추가 정보")).toBeInTheDocument();
    expect(screen.getByText("kept")).toBeInTheDocument();
    expect(screen.getByText("future-value")).toBeInTheDocument();
    expect(screen.getByText("nested-value")).toBeInTheDocument();
    expect(screen.getByText("invalid")).toBeInTheDocument();
    expect(screen.getByText("alpha")).toBeInTheDocument();
  });
});
