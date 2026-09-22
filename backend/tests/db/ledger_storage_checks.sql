-- Run with psql ON_ERROR_STOP against a DISPOSABLE database after migration 026.
-- Supabase-compatible roles must exist; test role must be able to SET ROLE service_role.
BEGIN;
SET LOCAL ROLE service_role;
DO $$
DECLARE
    manifest jsonb := jsonb_build_object('document_hash',repeat('a',64),'mapping_hash',repeat('b',64),
        'schema_version','ledger_statement_v1','observed_at','2026-09-11T00:00:00Z',
        'source_type','statement','source_count',1,'coverage_verified',false);
    sources jsonb := jsonb_build_array(jsonb_build_object('source_key','row-1',
        'payload_hash',repeat('c',64),'document_hash',repeat('a',64),'row_number',1));
    event jsonb := jsonb_build_object('account_id','test-ledger','event_key','deposit-1',
        'revision',1,'source_type','statement','source_key','row-1','source_record_hash',repeat('c',64),
        'quality','verified','event_type','deposit','precision','date_only','net_cash_amount','10',
        'observed_at','2026-09-11T00:00:00Z');
    result jsonb := '{"status":"validated","errors":[],"coverage_verified":false}';
    replay_result jsonb;
    inputs jsonb := '{"opening":{"account_id":"test-ledger"},"observed":null}';
    rejected boolean;
BEGIN
    PERFORM public.ledger_capture_import('test-ledger',repeat('d',64),manifest,sources);
    PERFORM public.ledger_capture_import('test-ledger',repeat('d',64),manifest,sources);
    IF (SELECT count(*) FROM public.ledger_source_records WHERE account_id='test-ledger') <> 1 THEN
        RAISE EXCEPTION 'idempotent capture failed';
    END IF;
    PERFORM public.ledger_publish_import('test-ledger',repeat('d',64),jsonb_build_array(event),result);
    PERFORM public.ledger_publish_import('test-ledger',repeat('d',64),jsonb_build_array(event),result);
    rejected := false;
    BEGIN
        PERFORM public.ledger_publish_import('test-ledger',repeat('d',64),'[]',result);
    EXCEPTION WHEN OTHERS THEN rejected := true; END;
    IF NOT rejected THEN RAISE EXCEPTION 'changed publication accepted'; END IF;
    rejected := false;
    BEGIN
        PERFORM public.ledger_capture_import('other-ledger',repeat('e',64),manifest,sources);
        PERFORM public.ledger_publish_import('other-ledger',repeat('e',64),jsonb_build_array(event),result);
    EXCEPTION WHEN OTHERS THEN rejected := true; END;
    IF NOT rejected OR EXISTS(SELECT 1 FROM public.ledger_accounts WHERE account_id='other-ledger') THEN
        RAISE EXCEPTION 'cross-account publication or rollback failed';
    END IF;
    rejected := false;
    BEGIN
        PERFORM public.ledger_capture_import('test-ledger',repeat('3',64),manifest,sources);
        PERFORM public.ledger_publish_import('test-ledger',repeat('3',64),
            jsonb_build_array(jsonb_set(event,'{net_cash_amount}','"20"')),result);
    EXCEPTION WHEN OTHERS THEN rejected := true; END;
    IF NOT rejected OR EXISTS(SELECT 1 FROM public.ledger_import_runs WHERE run_key=repeat('3',64))
        OR (SELECT payload->>'net_cash_amount' FROM public.ledger_events
            WHERE account_id='test-ledger' AND event_key='deposit-1') <> '10' THEN
        RAISE EXCEPTION 'conflicting revision preservation or rollback failed';
    END IF;
    rejected := false;
    BEGIN
        PERFORM public.ledger_capture_import('test-ledger',repeat('4',64),manifest,
            jsonb_set(sources,'{0,row_number}','2'));
    EXCEPTION WHEN OTHERS THEN rejected := true; END;
    IF NOT rejected OR EXISTS(SELECT 1 FROM public.ledger_import_runs WHERE run_key=repeat('4',64)) THEN
        RAISE EXCEPTION 'conflicting source preservation or rollback failed';
    END IF;
    PERFORM public.ledger_capture_import('test-ledger',repeat('5',64),
        jsonb_set(manifest,'{observed_at}','"2026-09-12T00:00:00Z"'),sources);
    PERFORM public.ledger_publish_import('test-ledger',repeat('5',64),
        jsonb_build_array(jsonb_set(event,'{observed_at}','"2026-09-12T00:00:00Z"')),result);
    PERFORM public.ledger_publish_import('test-ledger',repeat('5',64),
        jsonb_build_array(jsonb_set(event,'{observed_at}','"2026-09-12T00:00:00Z"')),result);
    IF (SELECT payload->>'observed_at' FROM public.ledger_events
        WHERE account_id='test-ledger' AND event_key='deposit-1') <> '2026-09-11T00:00:00Z'
        OR (SELECT events->0->>'observed_at' FROM public.ledger_import_results
            WHERE account_id='test-ledger' AND run_key=repeat('5',64)) <> '2026-09-12T00:00:00Z' THEN
        RAISE EXCEPTION 'later observation changed original event or was not preserved in import';
    END IF;
    rejected := false;
    BEGIN
        PERFORM public.ledger_capture_import('test-ledger',repeat('6',64),
            jsonb_set(manifest,'{observed_at}','"2026-09-10T00:00:00Z"'),sources);
        PERFORM public.ledger_publish_import('test-ledger',repeat('6',64),
            jsonb_build_array(jsonb_set(event,'{observed_at}','"2026-09-10T00:00:00Z"')),result);
    EXCEPTION WHEN OTHERS THEN rejected := true; END;
    IF NOT rejected OR EXISTS(SELECT 1 FROM public.ledger_import_runs WHERE run_key=repeat('6',64)) THEN
        RAISE EXCEPTION 'earlier observation was accepted or rollback failed';
    END IF;
    replay_result := jsonb_build_object('replay',jsonb_build_object('account_id','test-ledger',
        'coverage_verified',false,'return_rate',NULL,'journals',jsonb_build_array(jsonb_build_object(
        'event_key','deposit-1','revision',1,'evidence_hash',repeat('c',64),'currency','USD',
        'legs','[{"account":"cash","currency":"USD","amount":"10"},{"account":"external_capital","currency":"USD","amount":"-10"}]'::jsonb))),
        'reconciliation',NULL);
    PERFORM public.ledger_save_reconciliation('test-ledger',repeat('f',64),inputs,replay_result);
    PERFORM public.ledger_save_reconciliation('test-ledger',repeat('f',64),inputs,replay_result);
    IF (SELECT count(*) FROM public.ledger_postings WHERE account_id='test-ledger') <> 2 THEN
        RAISE EXCEPTION 'idempotent postings failed';
    END IF;
    rejected := false;
    BEGIN
        PERFORM public.ledger_save_reconciliation('test-ledger',repeat('1',64),inputs,
            jsonb_set(replay_result,'{replay,journals,0,legs,0,amount}','"10.0000000000001"'));
    EXCEPTION WHEN OTHERS THEN rejected := true; END;
    IF NOT rejected OR EXISTS(SELECT 1 FROM public.ledger_reconciliation_runs WHERE run_key=repeat('1',64)) THEN
        RAISE EXCEPTION 'precision rejection or rollback failed';
    END IF;
    rejected := false;
    BEGIN
        PERFORM public.ledger_save_reconciliation('test-ledger',repeat('2',64),inputs,
            jsonb_set(replay_result,'{replay,journals,0,legs,0,amount}','"11"'));
    EXCEPTION WHEN OTHERS THEN rejected := true; END;
    IF NOT rejected OR EXISTS(SELECT 1 FROM public.ledger_reconciliation_runs WHERE run_key=repeat('2',64)) THEN
        RAISE EXCEPTION 'unbalanced rejection or rollback failed';
    END IF;
    rejected := false;
    BEGIN UPDATE public.ledger_events SET payload=payload WHERE account_id='test-ledger';
    EXCEPTION WHEN insufficient_privilege THEN rejected := true; END;
    IF NOT rejected THEN RAISE EXCEPTION 'service role UPDATE privilege present'; END IF;
END;
$$;
RESET ROLE;
DO $$
DECLARE table_name text; rejected boolean;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['ledger_accounts','ledger_import_runs','ledger_source_records',
        'ledger_import_sources','ledger_events','ledger_import_results','ledger_reconciliation_runs','ledger_postings'] LOOP
        IF has_table_privilege('anon','public.'||table_name,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
            OR has_table_privilege('authenticated','public.'||table_name,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE') THEN
            RAISE EXCEPTION 'public table privilege leak: %',table_name;
        END IF;
        IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid=('public.'||table_name)::regclass) THEN
            RAISE EXCEPTION 'RLS disabled: %',table_name;
        END IF;
    END LOOP;
    INSERT INTO public.ledger_accounts(account_id) VALUES ('append-only-test');
    rejected := false;
    BEGIN UPDATE public.ledger_accounts SET account_id='changed' WHERE account_id='append-only-test';
    EXCEPTION WHEN raise_exception THEN rejected := true; END;
    IF NOT rejected THEN RAISE EXCEPTION 'owner mutation trigger failed'; END IF;
    IF has_function_privilege('anon','public.ledger_capture_import(text,text,jsonb,jsonb)','EXECUTE')
        OR has_function_privilege('authenticated','public.ledger_publish_import(text,text,jsonb,jsonb)','EXECUTE') THEN
        RAISE EXCEPTION 'RPC execute privilege leak';
    END IF;
END;
$$;
ROLLBACK;
