from pathlib import Path


def test_high_upside_speculative_stocks_migration_expands_both_constraints():
    migration = (
        Path("backend/app/db/migrations/021_add_high_upside_speculative_stocks_advisory.sql")
        .read_text(encoding="utf-8")
        .casefold()
    )

    assert "drop constraint if exists advisory_jobs_analysis_type_check" in migration
    assert "drop constraint if exists advisory_analyses_analysis_type_check" in migration
    assert migration.count("'high_upside_speculative_stocks'") == 3
    assert "create table if not exists public.advisory_capabilities" in migration
    assert "values ('high_upside_speculative_stocks', true)" in migration
