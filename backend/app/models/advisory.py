from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

AnalysisType: TypeAlias = Literal[
    "undervalued_us_stocks",
    "etf_rebalancing",
    "post_earnings_opportunities",
    "ai_beneficiaries",
    "high_dividend_etfs",
    "sec_filing_risk",
    "etf_overlap",
    "sector_outlook",
]
AdvisoryJobStatus: TypeAlias = Literal["queued", "running", "completed", "failed"]


class AdvisoryRequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    analysis_type: AnalysisType


class TickerScreenRequestBase(AdvisoryRequestBase):
    tickers: list[str] = Field(default_factory=list, max_length=50)
    max_results: int = Field(default=10, ge=1, le=50)


class UndervaluedUsStocksRequest(TickerScreenRequestBase):
    analysis_type: Literal["undervalued_us_stocks"]
    min_market_cap_usd: int | None = Field(default=None, ge=0)


class ETFPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    ticker: str = Field(min_length=1, max_length=20)
    weight_pct: float | None = Field(default=None, ge=0, le=100)


class EtfRebalancingRequest(AdvisoryRequestBase):
    analysis_type: Literal["etf_rebalancing"]
    positions: list[ETFPosition] = Field(default_factory=list, max_length=30)


class PostEarningsOpportunitiesRequest(TickerScreenRequestBase):
    analysis_type: Literal["post_earnings_opportunities"]
    lookback_days: int = Field(default=14, ge=1, le=90)


class AiBeneficiariesRequest(TickerScreenRequestBase):
    analysis_type: Literal["ai_beneficiaries"]
    themes: list[str] = Field(default_factory=list, max_length=20)


class HighDividendEtfsRequest(TickerScreenRequestBase):
    analysis_type: Literal["high_dividend_etfs"]
    min_distribution_yield_percent: float | None = Field(default=None, ge=0, le=100)


class SecFilingRiskRequest(AdvisoryRequestBase):
    analysis_type: Literal["sec_filing_risk"]
    ticker: str = Field(min_length=1, max_length=20)
    lookback_days: int = Field(default=90, ge=1, le=365)


class EtfOverlapRequest(AdvisoryRequestBase):
    analysis_type: Literal["etf_overlap"]
    positions: list[ETFPosition] = Field(min_length=1, max_length=30)


class SectorOutlookRequest(AdvisoryRequestBase):
    analysis_type: Literal["sector_outlook"]
    custom_proxies: dict[str, str] | None = None


AdvisoryJobRequest: TypeAlias = Annotated[
    UndervaluedUsStocksRequest
    | EtfRebalancingRequest
    | PostEarningsOpportunitiesRequest
    | AiBeneficiariesRequest
    | HighDividendEtfsRequest
    | SecFilingRiskRequest
    | EtfOverlapRequest
    | SectorOutlookRequest,
    Field(discriminator="analysis_type"),
]

_advisory_request_adapter = TypeAdapter(AdvisoryJobRequest)


def parse_advisory_job_request(payload: dict[str, Any]) -> AdvisoryJobRequest:
    return _advisory_request_adapter.validate_python(payload)


class AdvisoryJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    analysis_type: AnalysisType
    status: AdvisoryJobStatus
    request_hash: str
    analysis_id: str | None = None
    error_code: str | None = None
    message: str | None = None
    step_timings: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class AdvisoryAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str
    job_id: str
    analysis_type: AnalysisType
    request_hash: str
    request: dict[str, Any]
    result: dict[str, Any]
    created_at: str


class AdvisoryStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_status: Literal["available", "migration_required", "unavailable"]
    ai_narrative_status: Literal["configured", "not_configured"]
    migration_file: str


class AdvisoryResultBase(BaseModel):
    model_config = ConfigDict(extra="allow")

    analysis_type: AnalysisType
    evidence: list[dict[str, Any]]
    data_quality: dict[str, Any]
    disclaimer: str
    generated_at: str | None = None
    retrieved_at: str | None = None
    ai_narrative: dict[str, Any] | None = None
    ai_narrative_status: dict[str, Any] | None = None
    news_context: dict[str, Any] | None = None


class UndervaluedUsStocksResult(AdvisoryResultBase):
    analysis_type: Literal["undervalued_us_stocks"]
    rows: list[dict[str, Any]]
    top_candidates: list[dict[str, Any]]


class EtfRebalancingResult(AdvisoryResultBase):
    analysis_type: Literal["etf_rebalancing"]
    etfs: list[dict[str, Any]]
    current_weight_metadata: dict[str, Any]
    top10_overlap: list[dict[str, Any]]
    scenarios: list[dict[str, Any]]


class PostEarningsOpportunitiesResult(AdvisoryResultBase):
    analysis_type: Literal["post_earnings_opportunities"]
    rows: list[dict[str, Any]]
    rankings: list[dict[str, Any]]


class AiBeneficiariesResult(AdvisoryResultBase):
    analysis_type: Literal["ai_beneficiaries"]
    rows: list[dict[str, Any]]
    verified_ai_beneficiaries: list[dict[str, Any]]
    ai_theme_caution: list[dict[str, Any]]


class HighDividendEtfsResult(AdvisoryResultBase):
    analysis_type: Literal["high_dividend_etfs"]
    etfs: list[dict[str, Any]]
    caution_etfs: list[dict[str, Any]]
    relatively_stable_etfs: list[dict[str, Any]]
    beginner_explanation: str


class SecFilingRiskResult(AdvisoryResultBase):
    analysis_type: Literal["sec_filing_risk"]
    ticker: str
    latest_filings: list[dict[str, Any]]
    newly_emphasized_risks: list[Any]
    risk_categories: list[dict[str, Any]]
    management_caution_signals: list[Any]
    key_sentences: list[Any]
    risk_rating: str
    evaluation_status: str
    rating_reason: str


class EtfOverlapResult(AdvisoryResultBase):
    analysis_type: Literal["etf_overlap"]
    etfs: list[dict[str, Any]]
    pairwise_overlap: list[dict[str, Any]]
    actual_company_exposure: list[dict[str, Any]]
    style_exposure_approximation: dict[str, Any]
    requested_exposure_summary: dict[str, Any]
    diversification_assessment: dict[str, Any]
    rebalancing_plans: list[dict[str, Any]]
    target_weight_scenarios: list[dict[str, Any]]


class SectorOutlookResult(AdvisoryResultBase):
    analysis_type: Literal["sector_outlook"]
    proxy_universe: dict[str, str]
    sectors: list[dict[str, Any]]
    investor_portfolios: list[dict[str, Any]]
    market_input_coverage: dict[str, Any]


AdvisoryResult: TypeAlias = Annotated[
    UndervaluedUsStocksResult
    | EtfRebalancingResult
    | PostEarningsOpportunitiesResult
    | AiBeneficiariesResult
    | HighDividendEtfsResult
    | SecFilingRiskResult
    | EtfOverlapResult
    | SectorOutlookResult,
    Field(discriminator="analysis_type"),
]

_advisory_result_adapter = TypeAdapter(AdvisoryResult)


def validate_advisory_result(payload: dict[str, Any]) -> dict[str, Any]:
    result = _advisory_result_adapter.validate_python(payload)
    return result.model_dump(mode="json")
