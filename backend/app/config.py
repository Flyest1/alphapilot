import os
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict

from app.models.settings import Settings

APPLICATION_DEFAULT_ENV_MAP = {
    "domestic_report_time": "DOMESTIC_REPORT_TIME",
    "global_report_time": "GLOBAL_REPORT_TIME",
    "ai_provider": "AI_PROVIDER",
    "ai_model": "OPENAI_MODEL",
    "risk_profile": "RISK_PROFILE",
    "candidate_horizon": "CANDIDATE_HORIZON",
    "frontend_timezone": "FRONTEND_TIMEZONE",
    "stale_data_business_days": "STALE_DATA_BUSINESS_DAYS",
    "usd_krw_rate": "USD_KRW_RATE",
    "target_domestic_pct": "TARGET_DOMESTIC_PCT",
    "target_global_pct": "TARGET_GLOBAL_PCT",
    "target_cash_pct": "TARGET_CASH_PCT",
    "target_max_asset_pct": "TARGET_MAX_ASSET_PCT",
    "rebalance_band_pct": "REBALANCE_BAND_PCT",
    "risk_per_trade_pct": "RISK_PER_TRADE_PCT",
    "fee_rate_pct": "FEE_RATE_PCT",
    "kr_tax_rate_pct": "KR_TAX_RATE_PCT",
    "fx_spread_pct": "FX_SPREAD_PCT",
    "telegram_notify_report_completed": "TELEGRAM_NOTIFY_REPORT_COMPLETED",
    "telegram_notify_target_hit": "TELEGRAM_NOTIFY_TARGET_HIT",
    "telegram_notify_stop_hit": "TELEGRAM_NOTIFY_STOP_HIT",
    "telegram_notify_cycle_closed": "TELEGRAM_NOTIFY_CYCLE_CLOSED",
    "telegram_notify_drift_warning": "TELEGRAM_NOTIFY_DRIFT_WARNING",
}

INT_APPLICATION_FIELDS = {"stale_data_business_days"}
FLOAT_APPLICATION_FIELDS = {
    "usd_krw_rate",
    "target_domestic_pct",
    "target_global_pct",
    "target_cash_pct",
    "target_max_asset_pct",
    "rebalance_band_pct",
    "risk_per_trade_pct",
    "fee_rate_pct",
    "kr_tax_rate_pct",
    "fx_spread_pct",
}
BOOL_APPLICATION_FIELDS = {
    "telegram_notify_report_completed",
    "telegram_notify_target_hit",
    "telegram_notify_stop_hit",
    "telegram_notify_cycle_closed",
    "telegram_notify_drift_warning",
}


class EnvironmentSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_env: str | None
    supabase_url: str | None
    supabase_service_role_key: str | None
    supabase_anon_key: str | None
    openai_api_key: str | None
    scheduler_secret: str | None
    api_access_token: str | None
    frontend_origin: str | None
    market_data_provider_kr: str | None
    market_data_provider_us: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    toss_invest_client_id: str | None
    toss_invest_client_secret: str | None
    toss_invest_account_id: str | None
    fred_api_key: str | None = None
    sec_edgar_user_agent: str | None = None
    sec_edgar_cache_max_bytes: int | None = None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _is_placeholder(value: str | None) -> bool:
    if value is None:
        return True
    lowered = value.lower()
    return lowered.startswith("your-") or lowered.startswith("change-this")


@lru_cache
def get_environment_settings() -> EnvironmentSettings:
    load_dotenv()
    return EnvironmentSettings(
        app_env=_clean(os.getenv("APP_ENV")),
        supabase_url=_clean(os.getenv("SUPABASE_URL")),
        supabase_service_role_key=_clean(os.getenv("SUPABASE_SERVICE_ROLE_KEY")),
        supabase_anon_key=_clean(os.getenv("SUPABASE_ANON_KEY")),
        openai_api_key=_clean(os.getenv("OPENAI_API_KEY")),
        scheduler_secret=_clean(os.getenv("SCHEDULER_SECRET")),
        api_access_token=_clean(os.getenv("API_ACCESS_TOKEN")),
        frontend_origin=_clean(os.getenv("FRONTEND_ORIGIN")),
        market_data_provider_kr=_clean(os.getenv("MARKET_DATA_PROVIDER_KR")),
        market_data_provider_us=_clean(os.getenv("MARKET_DATA_PROVIDER_US")),
        telegram_bot_token=_clean(os.getenv("TELEGRAM_BOT_TOKEN")),
        telegram_chat_id=_clean(os.getenv("TELEGRAM_CHAT_ID")),
        toss_invest_client_id=_clean(os.getenv("TOSS_INVEST_CLIENT_ID")),
        toss_invest_client_secret=_clean(os.getenv("TOSS_INVEST_CLIENT_SECRET")),
        toss_invest_account_id=_clean(os.getenv("TOSS_INVEST_ACCOUNT_ID")),
        fred_api_key=_clean(os.getenv("FRED_API_KEY")),
        sec_edgar_user_agent=_clean(os.getenv("SEC_EDGAR_USER_AGENT")),
        sec_edgar_cache_max_bytes=_clean(os.getenv("SEC_EDGAR_CACHE_MAX_BYTES")),
    )


# Previous application defaults are upgraded wherever the env value is read, so reports,
# settings, advisory and status all resolve the same model.
LEGACY_DEFAULT_OPENAI_MODELS = frozenset({"gpt-5.4-mini", "gpt-5.6-luna"})
CURRENT_DEFAULT_OPENAI_MODEL = "gpt-6-luna"


def get_env_application_defaults() -> dict[str, Any]:
    load_dotenv()
    values: dict[str, Any] = {}
    for field_name, env_name in APPLICATION_DEFAULT_ENV_MAP.items():
        raw_value = _clean(os.getenv(env_name))
        if raw_value is None:
            continue
        if field_name in INT_APPLICATION_FIELDS:
            values[field_name] = int(raw_value)
        elif field_name in FLOAT_APPLICATION_FIELDS:
            values[field_name] = float(raw_value)
        elif field_name in BOOL_APPLICATION_FIELDS:
            values[field_name] = raw_value.lower() in {"1", "true", "yes", "on"}
        else:
            values[field_name] = raw_value
    if values.get("ai_model") in LEGACY_DEFAULT_OPENAI_MODELS:
        values["ai_model"] = CURRENT_DEFAULT_OPENAI_MODEL
    return values


def load_application_settings(repository: Any) -> Settings:
    """Resolve settings in the documented order: stored row, then .env, then defaults."""
    return resolve_application_settings(repository.get_settings(), get_env_application_defaults())


def persist_usd_krw_rate(repository: Any, app_settings: Settings, rate: float) -> dict[str, Any]:
    """Store a refreshed FX rate without overwriting other settings.

    An existing row only receives ``usd_krw_rate`` so a concurrent user save is not reverted.
    Without a row, the fully resolved settings are inserted; a partial insert would otherwise
    pick up SQL column defaults that outrank the operator's ``.env`` values.
    """
    if repository.get_settings():
        return repository.upsert_settings({"usd_krw_rate": rate})
    values = app_settings.model_dump(mode="json", exclude={"created_at", "updated_at"})
    values["usd_krw_rate"] = rate
    return repository.upsert_settings(values)


def resolve_application_settings(
    settings_row: dict[str, Any] | None,
    env_defaults: dict[str, Any] | None = None,
) -> Settings:
    values = Settings().model_dump()
    values.update(env_defaults if env_defaults is not None else get_env_application_defaults())

    if settings_row:
        for field_name in APPLICATION_DEFAULT_ENV_MAP:
            row_value = settings_row.get(field_name)
            if row_value is not None:
                values[field_name] = row_value
        values["created_at"] = settings_row.get("created_at")
        values["updated_at"] = settings_row.get("updated_at")

    return Settings.model_validate(values)


def is_supabase_configured(env: EnvironmentSettings | None = None) -> bool:
    current = env or get_environment_settings()
    return not (
        _is_placeholder(current.supabase_url) or _is_placeholder(current.supabase_service_role_key)
    )


def clear_settings_cache() -> None:
    get_environment_settings.cache_clear()
