from pathlib import Path


def test_profit_taking_review_migration_expands_both_advisory_constraints():
    migration = Path(
        "backend/app/db/migrations/020_add_profit_taking_review_advisory.sql"
    ).read_text(encoding="utf-8")

    assert "drop constraint if exists advisory_jobs_analysis_type_check" in migration
    assert "drop constraint if exists advisory_analyses_analysis_type_check" in migration
    assert migration.count("'profit_taking_review'") == 3
    assert "alter table public.advisory_jobs" in migration
    assert "alter table public.advisory_analyses" in migration
    assert "create table if not exists public.advisory_capabilities" in migration
    assert "values ('profit_taking_review', true)" in migration
    assert migration.rfind("values ('profit_taking_review', true)") > migration.rfind(
        "alter table public.advisory_analyses"
    )
