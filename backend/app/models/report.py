from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


class AssetStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    name: str
    current_price: Optional[float] = None
    action: Literal["BUY", "HOLD", "REDUCE", "SELL", "WATCH"]
    confidence: int = Field(ge=0, le=100)  # integer 0..100
    buy_range_low: Optional[float] = None
    buy_range_high: Optional[float] = None
    sell_range_low: Optional[float] = None
    sell_range_high: Optional[float] = None
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    reasoning: str
    risk: str
    invalidation_condition: str


class MarketSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    key_indices: list[dict] = Field(default_factory=list)
    macro_factors: list[str] = Field(default_factory=list)
    # news_factors intentionally omitted. Approved news/trend context may be folded into
    # existing allowed fields, but the schema must not add a separate news_factors field.


class PortfolioSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_market_value: float
    total_return_rate: float
    risk_level: Literal["low", "medium", "high"]
    allocation_comment: str


class ReportContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_type: Literal["domestic", "global"]
    generated_at: str  # ISO 8601 with timezone
    market_summary: MarketSummary
    portfolio_summary: PortfolioSummary
    key_risks: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    asset_strategies: list[AssetStrategy] = Field(default_factory=list)
    disclaimer: str
