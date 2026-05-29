from pydantic import BaseModel, ConfigDict, Field


class PortfolioSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_market_value: float = 0
    total_cost: float = 0
    total_profit_loss: float = 0
    total_return_rate: float = 0
    daily_profit_loss: float = 0
    daily_return_rate: float = 0
    domestic_value: float = 0
    global_value: float = 0
    cash_value: float = 0
    base_currency: str = "KRW"
    usd_krw_rate: float = 1400
    daily_asset_changes: list[dict] = Field(default_factory=list)
    asset_allocation: list[dict] = Field(default_factory=list)
    asset_returns: list[dict] = Field(default_factory=list)
    latest_report_summary: str | None = None
