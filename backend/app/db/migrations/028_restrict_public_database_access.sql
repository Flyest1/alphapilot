-- Single-user FastAPI is the only application entry point; it uses service_role.
-- Permission-only migration: no row, column, policy, or function body is rewritten.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

REVOKE CREATE ON SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC, anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC, anon, authenticated;

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'assets', 'reports', 'strategies', 'settings', 'performance_logs',
        'candidate_assets', 'report_jobs', 'portfolio_snapshots',
        'recommendation_cycles', 'market_data_cache', 'candidate_universe',
        'notifications', 'signal_model_versions', 'signal_model_assignments',
        'signal_model_evaluation_runs', 'signal_model_evaluation_observations',
        'signal_model_report_links', 'advisory_jobs', 'advisory_analyses',
        'advisory_capabilities'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        -- No client policy: intentional default deny. service_role bypasses RLS.
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO service_role', table_name
        );
    END LOOP;
END;
$$;

-- Never broaden ledger SELECT/INSERT privileges or weaken immutable triggers.
-- These four legacy trigger functions are internal, like the existing ledger/Toss RPCs.
REVOKE ALL ON FUNCTION public.prevent_signal_model_version_mutation(),
    public.validate_signal_model_evaluation_run(),
    public.validate_signal_model_evaluation_observation(),
    public.validate_signal_model_report_link() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.prevent_signal_model_version_mutation(),
    public.validate_signal_model_evaluation_run(),
    public.validate_signal_model_evaluation_observation(),
    public.validate_signal_model_report_link() TO service_role;

-- Existing bodies use unqualified application tables. Pin trusted schemas and put
-- pg_temp last, so caller-created temporary relations cannot shadow those tables.
ALTER FUNCTION public.prevent_signal_model_version_mutation()
    SET search_path = pg_catalog, public, pg_temp;
ALTER FUNCTION public.validate_signal_model_evaluation_run()
    SET search_path = pg_catalog, public, pg_temp;
ALTER FUNCTION public.validate_signal_model_evaluation_observation()
    SET search_path = pg_catalog, public, pg_temp;
ALTER FUNCTION public.validate_signal_model_report_link()
    SET search_path = pg_catalog, public, pg_temp;

-- Application migrations run as postgres. Do not change Supabase-managed owners
-- or auth/storage schemas. Existing service_role defaults remain untouched.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    REVOKE ALL ON FUNCTIONS FROM PUBLIC, anon, authenticated;
-- PostgreSQL's implicit PUBLIC EXECUTE is global: a schema-local REVOKE alone
-- cannot remove it. New postgres-owned functions in any schema need explicit grants.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

NOTIFY pgrst, 'reload schema';
COMMIT;
