from pydantic import BaseModel, ConfigDict

from app.models.asset import Market


class CandidateAssetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: Market
    ticker: str
    name: str
    currency: str = "KRW"
    memo: str | None = None
    is_active: bool = True


class CandidateAssetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    market: Market | None = None
    ticker: str | None = None
    name: str | None = None
    currency: str | None = None
    memo: str | None = None
    is_active: bool | None = None


class CandidateAssetRead(CandidateAssetCreate):
    id: str
    created_at: str | None = None
    updated_at: str | None = None
