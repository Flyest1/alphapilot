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
}

INFRASTRUCTURE_ENV_KEYS = (
    "APP_ENV",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_ANON_KEY",
    "OPENAI_API_KEY",
    "SCHEDULER_SECRET",
    "API_ACCESS_TOKEN",
    "FRONTEND_ORIGIN",
)


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
    )


def get_env_application_defaults() -> dict[str, Any]:
    load_dotenv()
    values: dict[str, Any] = {}
    for field_name, env_name in APPLICATION_DEFAULT_ENV_MAP.items():
        raw_value = _clean(os.getenv(env_name))
        if raw_value is None:
            continue
        if field_name == "stale_data_business_days":
            values[field_name] = int(raw_value)
        elif field_name == "usd_krw_rate":
            values[field_name] = float(raw_value)
        else:
            values[field_name] = raw_value
    return values


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
