from pathlib import Path

from app.config import resolve_application_settings
from app.models.settings import Settings


def test_application_defaults_match_env_example_and_sql_defaults():
    root = Path(__file__).resolve().parents[2]
    env_text = (root / "backend" / ".env.example").read_text()
    sql_text = (
        root / "backend" / "app" / "db" / "migrations" / "001_initial_schema.sql"
    ).read_text()
    defaults = Settings()

    assert f"DOMESTIC_REPORT_TIME={defaults.domestic_report_time}" in env_text
    assert f"GLOBAL_REPORT_TIME={defaults.global_report_time}" in env_text
    assert f"AI_PROVIDER={defaults.ai_provider}" in env_text
    assert f"OPENAI_MODEL={defaults.ai_model}" in env_text
    assert f"RISK_PROFILE={defaults.risk_profile}" in env_text
    assert f"CANDIDATE_HORIZON={defaults.candidate_horizon}" in env_text
    assert f"FRONTEND_TIMEZONE={defaults.frontend_timezone}" in env_text
    assert f"STALE_DATA_BUSINESS_DAYS={defaults.stale_data_business_days}" in env_text
    assert f"USD_KRW_RATE={int(defaults.usd_krw_rate)}" in env_text

    assert f"domestic_report_time text default '{defaults.domestic_report_time}'" in sql_text
    assert f"global_report_time text default '{defaults.global_report_time}'" in sql_text
    assert f"ai_provider text default '{defaults.ai_provider}'" in sql_text
    assert f"ai_model text default '{defaults.ai_model}'" in sql_text
    assert f"risk_profile text default '{defaults.risk_profile}'" in sql_text
    assert f"candidate_horizon text default '{defaults.candidate_horizon}'" in sql_text
    assert f"frontend_timezone text default '{defaults.frontend_timezone}'" in sql_text
    assert f"stale_data_business_days int default {defaults.stale_data_business_days}" in sql_text
    assert f"usd_krw_rate numeric default {int(defaults.usd_krw_rate)}" in sql_text


def test_settings_row_overrides_env_defaults():
    resolved = resolve_application_settings(
        {
            "ai_model": "table-model",
            "risk_profile": "aggressive",
            "candidate_horizon": "short",
            "usd_krw_rate": 1450,
        },
        {
            "ai_model": "env-model",
            "risk_profile": "balanced",
            "candidate_horizon": "long",
            "usd_krw_rate": 1300,
        },
    )

    assert resolved.ai_model == "table-model"
    assert resolved.risk_profile == "aggressive"
    assert resolved.candidate_horizon == "short"
    assert resolved.usd_krw_rate == 1450


def test_notification_defaults_match_env_example_and_migration():
    root = Path(__file__).resolve().parents[2]
    env_text = (root / "backend" / ".env.example").read_text()
    migration = (
        root / "backend" / "app" / "db" / "migrations" / "013_create_notifications.sql"
    ).read_text()
    defaults = Settings()

    for field in (
        "telegram_notify_report_completed",
        "telegram_notify_target_hit",
        "telegram_notify_stop_hit",
        "telegram_notify_cycle_closed",
        "telegram_notify_drift_warning",
    ):
        env_name = field.upper()
        assert getattr(defaults, field) is False
        assert f"{env_name}=false" in env_text
        assert f"add column if not exists {field} boolean default false" in migration


def test_toss_invest_infrastructure_env_keys_are_documented():
    root = Path(__file__).resolve().parents[2]
    env_text = (root / "backend" / ".env.example").read_text()
    agents_text = (root / "AGENTS.md").read_text()

    for name in (
        "TOSS_INVEST_CLIENT_ID",
        "TOSS_INVEST_CLIENT_SECRET",
        "TOSS_INVEST_ACCOUNT_ID",
    ):
        assert f"{name}=" in env_text
        assert name in agents_text
