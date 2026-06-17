from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Market = Literal["KR", "US", "CASH", "ETF"]
AssetSource = Literal["manual", "toss_api"]


class AssetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: Market
    ticker: str
    name: str
    quantity: float = Field(ge=0)
    avg_price: float = Field(ge=0)
    currency: str = "KRW"
    memo: str | None = None
    sector: str | None = None


class AssetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: Market | None = None
    ticker: str | None = None
    name: str | None = None
    quantity: float | None = Field(default=None, ge=0)
    avg_price: float | None = Field(default=None, ge=0)
    currency: str | None = None
    memo: str | None = None
    sector: str | None = None


class AssetRead(AssetCreate):
    id: str
    source: AssetSource = "manual"
    external_provider: str | None = None
    external_account_id: str | None = None
    external_asset_key: str | None = None
    synced_at: str | None = None
    external_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
