from pathlib import Path

from app.config import resolve_application_settings
from app.models.settings import Settings


def test_application_defaults_match_env_example_and_sql_defaults():
    root = Path(__file__).resolve().parents[2]
    env_text = (root / "backend" / ".env.example").read_text(encoding="utf-8")
    sql_text = (
        root / "backend" / "app" / "db" / "migrations" / "001_initial_schema.sql"
    ).read_text(encoding="utf-8")
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
    env_text = (root / "backend" / ".env.example").read_text(encoding="utf-8")
    migration = (
        root / "backend" / "app" / "db" / "migrations" / "013_create_notifications.sql"
    ).read_text(encoding="utf-8")
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
    env_text = (root / "backend" / ".env.example").read_text(encoding="utf-8")
    agents_text = (root / "AGENTS.md").read_text(encoding="utf-8")

    for name in (
        "TOSS_INVEST_CLIENT_ID",
        "TOSS_INVEST_CLIENT_SECRET",
        "TOSS_INVEST_ACCOUNT_ID",
    ):
        assert f"{name}=" in env_text
        assert name in agents_text


def test_advisory_provider_infrastructure_env_keys_are_documented():
    root = Path(__file__).resolve().parents[2]
    env_text = (root / "backend" / ".env.example").read_text(encoding="utf-8")
    oracle_env_text = (root / "deploy" / "oracle" / "backend.env.example").read_text(
        encoding="utf-8"
    )
    agents_text = (root / "AGENTS.md").read_text(encoding="utf-8")

    for name in ("FRED_API_KEY", "SEC_EDGAR_USER_AGENT", "SEC_EDGAR_CACHE_MAX_BYTES"):
        assert f"{name}=" in env_text
        assert f"{name}=" in oracle_env_text
        assert name in agents_text


def test_legacy_env_model_is_upgraded_for_every_resolver(monkeypatch):
    from app.config import CURRENT_DEFAULT_OPENAI_MODEL, get_env_application_defaults

    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.6-luna")
    assert get_env_application_defaults()["ai_model"] == CURRENT_DEFAULT_OPENAI_MODEL
    monkeypatch.setenv("OPENAI_MODEL", "custom-model")
    assert get_env_application_defaults()["ai_model"] == "custom-model"


def test_fx_refresh_writes_only_rate_to_existing_settings_row():
    from app.config import persist_usd_krw_rate, resolve_application_settings
    from app.db.supabase_client import InMemoryRepository

    repository = InMemoryRepository()
    repository.upsert_settings({"risk_profile": "aggressive"})
    stale_view = resolve_application_settings(
        {"risk_profile": "conservative"}, {"risk_profile": "conservative"}
    )

    persist_usd_krw_rate(repository, stale_view, 1385.5)

    stored = repository.get_settings()
    assert stored["usd_krw_rate"] == 1385.5
    assert stored["risk_profile"] == "aggressive"


def test_fx_refresh_inserts_resolved_settings_when_no_row_exists():
    from app.config import persist_usd_krw_rate, resolve_application_settings
    from app.db.supabase_client import InMemoryRepository

    repository = InMemoryRepository()
    resolved = resolve_application_settings(None, {"risk_profile": "aggressive"})

    persist_usd_krw_rate(repository, resolved, 1390.0)

    stored = repository.get_settings()
    assert stored["usd_krw_rate"] == 1390.0
    assert stored["risk_profile"] == "aggressive"
    assert stored["ai_model"] == resolved.ai_model
