from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domestic_report_time: str = "08:30"
    global_report_time: str = "22:30"
    ai_provider: str = "openai"
    ai_model: str = "gpt-5.4-mini"
    risk_profile: Literal["conservative", "balanced", "aggressive"] = "balanced"
    candidate_horizon: Literal["short", "medium", "long"] = "medium"
    frontend_timezone: str = "Asia/Seoul"
    stale_data_business_days: int = Field(default=2, ge=0)
    usd_krw_rate: float = Field(default=1400, gt=0)
    created_at: str | None = None
    updated_at: str | None = None


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domestic_report_time: str | None = None
    global_report_time: str | None = None
    ai_provider: str | None = None
    ai_model: str | None = None
    risk_profile: Literal["conservative", "balanced", "aggressive"] | None = None
    candidate_horizon: Literal["short", "medium", "long"] | None = None
    frontend_timezone: str | None = None
    stale_data_business_days: int | None = Field(default=None, ge=0)
    usd_krw_rate: float | None = Field(default=None, gt=0)
