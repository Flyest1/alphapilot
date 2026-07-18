from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domestic_report_time: str = "08:30"
    global_report_time: str = "22:30"
    ai_provider: str = "openai"
    ai_model: str = "gpt-5.6-luna"
    risk_profile: Literal["conservative", "balanced", "aggressive"] = "balanced"
    candidate_horizon: Literal["short", "medium", "long"] = "medium"
    frontend_timezone: str = "Asia/Seoul"
    stale_data_business_days: int = Field(default=2, ge=0)
    usd_krw_rate: float = Field(default=1400, gt=0)
    # Phase 5-2: 목표 배분(합계 100 권장)과 리밸런스 임계치
    target_domestic_pct: float = Field(default=40, ge=0, le=100)
    target_global_pct: float = Field(default=40, ge=0, le=100)
    target_cash_pct: float = Field(default=20, ge=0, le=100)
    target_max_asset_pct: float = Field(default=25, gt=0, le=100)
    rebalance_band_pct: float = Field(default=5, ge=0, le=50)
    # Phase 5-3: 1회 추천당 감수할 손실 한도 (총자산 대비 %)
    risk_per_trade_pct: float = Field(default=1.0, gt=0, le=10)
    # Phase 5-4: 비용 인지 수익률 추정용 (모두 편도 %)
    fee_rate_pct: float = Field(default=0.015, ge=0, le=5)
    kr_tax_rate_pct: float = Field(default=0.18, ge=0, le=5)
    fx_spread_pct: float = Field(default=0.5, ge=0, le=5)
    telegram_notify_report_completed: bool = False
    telegram_notify_target_hit: bool = False
    telegram_notify_stop_hit: bool = False
    telegram_notify_cycle_closed: bool = False
    telegram_notify_drift_warning: bool = False
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
    target_domestic_pct: float | None = Field(default=None, ge=0, le=100)
    target_global_pct: float | None = Field(default=None, ge=0, le=100)
    target_cash_pct: float | None = Field(default=None, ge=0, le=100)
    target_max_asset_pct: float | None = Field(default=None, gt=0, le=100)
    rebalance_band_pct: float | None = Field(default=None, ge=0, le=50)
    risk_per_trade_pct: float | None = Field(default=None, gt=0, le=10)
    fee_rate_pct: float | None = Field(default=None, ge=0, le=5)
    kr_tax_rate_pct: float | None = Field(default=None, ge=0, le=5)
    fx_spread_pct: float | None = Field(default=None, ge=0, le=5)
    telegram_notify_report_completed: bool | None = None
    telegram_notify_target_hit: bool | None = None
    telegram_notify_stop_hit: bool | None = None
    telegram_notify_cycle_closed: bool | None = None
    telegram_notify_drift_warning: bool | None = None
