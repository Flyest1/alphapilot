"""Real permission tests in a newly created, disposable loopback PostgreSQL database.

Opt in with DATABASE_ACCESS_TEST_PSQL (path to psql). Only 127.0.0.1:55439 and
ledger_test are used; no app .env or operating credentials are loaded. The test
database is retained for inspection locally and discarded with the CI service.
"""

import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

PSQL = os.environ.get("DATABASE_ACCESS_TEST_PSQL")
pytestmark = pytest.mark.skipif(not PSQL, reason="Disposable local PostgreSQL not configured")
MIGRATIONS = Path(__file__).resolve().parents[2] / "app/db/migrations"


def query(database, statement, *, success=True):
    result = subprocess.run(
        [
            PSQL,
            "-X",
            "-qAt",
            "-h",
            "127.0.0.1",
            "-p",
            "55439",
            "-U",
            "ledger_test",
            "-d",
            database,
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input=statement,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if success:
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()
    assert result.returncode != 0, "Expected SQL to be denied"
    assert "permission denied" in result.stderr, result.stderr
    return result.stderr


def snapshot(database):
    tables = query(
        database,
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename",
    ).splitlines()
    return {
        table: query(
            database,
            f"SELECT md5(coalesce(string_agg(to_jsonb(t)::text, '' "
            f"ORDER BY to_jsonb(t)::text), '')) FROM public.{table} t",
        )
        for table in tables
    }


@pytest.fixture(scope="module")
def database():
    # Roles are cluster-scoped; reuse only on this explicit disposable test endpoint.
    query(
        "postgres",
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='postgres') THEN
            CREATE ROLE postgres NOLOGIN BYPASSRLS;
          END IF;
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='anon') THEN
            CREATE ROLE anon NOLOGIN;
          END IF;
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='authenticated') THEN
            CREATE ROLE authenticated NOLOGIN;
          END IF;
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='service_role') THEN
            CREATE ROLE service_role NOLOGIN BYPASSRLS;
          END IF;
        END $$;
        """,
    )
    name = "alphapilot_access_test_" + uuid4().hex
    query("postgres", f"CREATE DATABASE {name} OWNER postgres")
    query(
        name,
        """
        SET ROLE postgres;
        GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES
          TO anon, authenticated, service_role;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES
          TO anon, authenticated, service_role;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS
          TO anon, authenticated, service_role;
        """,
    )
    for migration in sorted(MIGRATIONS.glob("*.sql")):
        if int(migration.name[:3]) < 28:
            query(name, "SET ROLE postgres;\n" + migration.read_text(encoding="utf-8"))
    query(
        name,
        """
        SET ROLE service_role;
        INSERT INTO public.assets(market,ticker,name,quantity,avg_price)
          VALUES('KR','SYNTHETIC','permission fixture',1,100);
        """,
    )
    assert query(name, "SET ROLE anon; SELECT count(*) FROM public.assets") == "1"
    before = snapshot(name)
    migration = (MIGRATIONS / "028_restrict_public_database_access.sql").read_text(encoding="utf-8")
    # Applying twice also verifies idempotency without modifying source rows.
    query(name, "SET ROLE postgres;\n" + migration)
    query(name, "SET ROLE postgres;\n" + migration)
    assert snapshot(name) == before
    return name


@pytest.mark.parametrize("role", ["anon", "authenticated"])
@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM public.assets",
        "INSERT INTO public.assets(market,ticker,name,quantity,avg_price) "
        "VALUES('KR','DENIED','denied',1,1)",
        "UPDATE public.assets SET quantity=2",
        "DELETE FROM public.assets",
        "TRUNCATE public.assets",
        "SELECT public.ledger_read_account('nonexistent')",
        "SELECT public.reconcile_toss_holdings('nonexistent',now(),'[]'::jsonb)",
        "CREATE TABLE public.denied_table(id int)",
    ],
)
def test_clients_cannot_read_write_or_call_rpc(database, role, statement):
    query(database, f"BEGIN; SET LOCAL ROLE {role}; {statement}; ROLLBACK;", success=False)


def test_all_tables_and_functions_are_server_only(database):
    result = json.loads(
        query(
            database,
            """
            SELECT json_build_object(
              'table_count', (SELECT count(*) FROM pg_tables WHERE schemaname='public'),
              'unsafe_tables', (SELECT count(*) FROM pg_class c
                WHERE c.relnamespace='public'::regnamespace AND c.relkind='r'
                AND (NOT c.relrowsecurity
                  OR has_table_privilege('anon', c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
                  OR has_table_privilege('authenticated', c.oid,
                    'SELECT,INSERT,UPDATE,DELETE,TRUNCATE'))),
              'unsafe_functions', (SELECT count(*) FROM pg_proc p
                WHERE p.pronamespace='public'::regnamespace
                AND (has_function_privilege('anon', p.oid, 'EXECUTE')
                  OR has_function_privilege('authenticated', p.oid, 'EXECUTE'))),
              'mutable_paths', (SELECT count(*) FROM pg_proc p
                WHERE p.pronamespace='public'::regnamespace AND p.proconfig IS NULL));
            """,
        )
    )
    assert result == {
        "table_count": 29,
        "unsafe_tables": 0,
        "unsafe_functions": 0,
        "mutable_paths": 0,
    }


def test_server_crud_and_read_rpc_still_work(database):
    assert (
        query(
            database,
            """
        BEGIN;
        SET LOCAL ROLE service_role;
        INSERT INTO public.assets(market,ticker,name,quantity,avg_price)
          VALUES('US','SERVER','server fixture',1,10);
        UPDATE public.assets SET quantity=2 WHERE ticker='SERVER';
        SELECT quantity FROM public.assets WHERE ticker='SERVER';
        DELETE FROM public.assets WHERE ticker='SERVER';
        SELECT jsonb_array_length(public.ledger_read_review_state('nonexistent')->'reviews');
        ROLLBACK;
        """,
        )
        == "2\n0"
    )
    assert (
        query(
            database,
            """
        SELECT count(*) FROM pg_tables t WHERE schemaname='public'
          AND NOT has_table_privilege('service_role',
            format('%I.%I', schemaname, tablename), 'SELECT');
        """,
        )
        == "0"
    )


def test_ledger_mutation_privileges_remain_denied(database):
    assert (
        query(
            database,
            """
        SELECT count(*) FROM pg_tables t WHERE schemaname='public'
          AND tablename LIKE 'ledger_%'
          AND has_table_privilege('service_role',
            format('%I.%I', schemaname, tablename), 'UPDATE,DELETE,TRUNCATE');
        """,
        )
        == "0"
    )
    query(database, "SET ROLE service_role; DELETE FROM public.ledger_accounts", success=False)


def test_new_postgres_owned_objects_do_not_reopen_access(database):
    assert (
        query(
            database,
            """
        BEGIN;
        SET LOCAL ROLE postgres;
        CREATE TABLE public.future_private(id int);
        CREATE SEQUENCE public.future_private_seq;
        CREATE FUNCTION public.future_private_fn() RETURNS int
          LANGUAGE sql AS 'SELECT 1';
        SELECT has_table_privilege('anon','public.future_private','SELECT')
          OR has_table_privilege('authenticated','public.future_private','INSERT')
          OR has_sequence_privilege('anon','public.future_private_seq','USAGE')
          OR has_function_privilege('anon','public.future_private_fn()','EXECUTE')
          OR has_function_privilege('authenticated','public.future_private_fn()','EXECUTE');
        SELECT has_table_privilege('service_role','public.future_private','SELECT')
          AND has_function_privilege('service_role','public.future_private_fn()','EXECUTE');
        ROLLBACK;
        """,
        )
        == "f\nt"
    )


def test_rls_still_denies_rows_if_select_is_accidentally_granted(database):
    assert (
        query(
            database,
            """
        BEGIN;
        GRANT SELECT ON public.assets TO anon;
        SET LOCAL ROLE anon;
        SELECT count(*) FROM public.assets;
        ROLLBACK;
        """,
        )
        == "0"
    )


def test_server_toss_reconciliation_preserves_manual_asset(database):
    assert (
        query(
            database,
            """
        BEGIN;
        SET LOCAL ROLE service_role;
        SELECT public.reconcile_toss_holdings('local-fixture',now(),
          '[{"market":"CASH","ticker":"KRW","name":"fixture cash",
             "external_asset_key":"CASH:KRW","quantity":100,"avg_price":1,"currency":"KRW",
             "external_payload":{}},
            {"market":"CASH","ticker":"USD","name":"fixture cash",
             "external_asset_key":"CASH:USD","quantity":10,"avg_price":1,"currency":"USD",
             "external_payload":{}}]'
        )->>'created_count';
        SELECT count(*) FROM public.assets WHERE ticker='SYNTHETIC';
        ROLLBACK;
        """,
        )
        == "2\n1"
    )


def test_signal_triggers_keep_validation_and_ignore_temp_table_shadowing(database):
    query(
        database,
        """
        BEGIN;
        SET LOCAL ROLE service_role;
        CREATE TEMP TABLE signal_model_versions AS SELECT * FROM public.signal_model_versions
          WHERE false;
        CREATE TEMP TABLE signal_model_assignments AS SELECT * FROM public.signal_model_assignments
          WHERE false;
        CREATE TEMP TABLE signal_model_evaluation_runs AS
          SELECT * FROM public.signal_model_evaluation_runs WHERE false;
        DO $$
        DECLARE
          champion public.signal_model_versions%ROWTYPE;
          challenger_id uuid;
          run_id uuid;
          report_id uuid;
        BEGIN
          SELECT * INTO champion FROM public.signal_model_versions WHERE version='v1';
          INSERT INTO public.signal_model_versions(model_key,version,config,config_sha256)
            VALUES('local-test','v2','{}',repeat('a',64)) RETURNING id INTO challenger_id;
          INSERT INTO public.signal_model_evaluation_runs(
            champion_model_version_id,challenger_model_version_id,
            champion_config_sha256,challenger_config_sha256,report_type,trigger_type,
            decision_at,started_at,ends_at,input_snapshot,input_sha256)
            VALUES(champion.id,challenger_id,champion.config_sha256,repeat('a',64),
              'domestic','scheduled',now(),now(),now()+interval '12 weeks','{}',repeat('b',64))
            RETURNING id INTO run_id;
          INSERT INTO public.signal_model_evaluation_observations(
            evaluation_run_id,model_version_id,arm,observation_key,observed_at,
            market,ticker,action,horizon)
            VALUES(run_id,champion.id,'champion','fixture',now(),'KR','TEST','WATCH','medium');
          INSERT INTO public.reports(report_type,title,content)
            VALUES('domestic','local fixture','{}') RETURNING id INTO report_id;
          INSERT INTO public.signal_model_report_links(
            report_id,generation_source,is_official_sample,champion_assignment_id,
            champion_version_id,report_inputs_snapshot,input_sha256)
            SELECT report_id,'manual',false,id,champion.id,'{}',repeat('c',64)
            FROM public.signal_model_assignments WHERE role='champion' AND ended_at IS NULL;
          BEGIN
            UPDATE public.signal_model_versions SET version='changed' WHERE id=champion.id;
            RAISE EXCEPTION 'immutable trigger did not reject update';
          EXCEPTION WHEN raise_exception THEN
            IF SQLERRM <> 'signal_model_versions are immutable' THEN RAISE; END IF;
          END;
          BEGIN
            UPDATE public.signal_model_evaluation_runs SET champion_config_sha256=repeat('d',64)
              WHERE id=run_id;
            RAISE EXCEPTION 'hash trigger did not reject update';
          EXCEPTION WHEN raise_exception THEN
            IF SQLERRM <> 'evaluation run config hashes do not match model versions'
              THEN RAISE; END IF;
          END;
        END $$;
        ROLLBACK;
        """,
    )
