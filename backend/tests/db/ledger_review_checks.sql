-- Disposable PostgreSQL only, after 026 and 027. Every fixture is rolled back.
BEGIN;
CREATE FUNCTION pg_temp.review_must_fail(statement text) RETURNS void LANGUAGE plpgsql AS $$
DECLARE failed boolean := false;
BEGIN
    BEGIN EXECUTE statement; EXCEPTION WHEN OTHERS THEN failed := true; END;
    IF NOT failed THEN RAISE EXCEPTION 'unexpected success: %',statement; END IF;
END;
$$;
SET LOCAL ROLE service_role;
DO $$
DECLARE
    a text := 'review-sql-fixture'; b text := 'review-sql-other'; i integer;
    manifest jsonb; event jsonb; request jsonb; first_row jsonb; next_row jsonb; duplicate_request jsonb;
BEGIN
    INSERT INTO public.ledger_accounts(account_id) VALUES(a),(b);
    FOR i IN 1..5 LOOP
        manifest := jsonb_build_object('document_hash',repeat(CASE WHEN i=4 THEN 'b' ELSE 'a' END,64),
            'source_count',1,'observed_at','2026-09-01T00:00:00Z');
        INSERT INTO public.ledger_import_runs(account_id,run_key,manifest)
            VALUES(CASE WHEN i=5 THEN b ELSE a END,repeat(i::text,64),manifest);
        IF i<>1 THEN
            INSERT INTO public.ledger_import_results(account_id,run_key,result,events)
                VALUES(CASE WHEN i=5 THEN b ELSE a END,repeat(i::text,64),
                    jsonb_build_object('status',CASE WHEN i=3 THEN 'partial' ELSE 'validated' END,'errors','[]'::jsonb),
                    '[{}]'::jsonb);
        END IF;
    END LOOP;
    request := jsonb_build_object('kind','import_resolution','source_run_key',repeat('1',64),
        'replacement_run_key',repeat('2',64),'decision','resolve','reason_code','corrected_mapping');
    PERFORM pg_temp.review_must_fail(format('SELECT public.ledger_record_review(%L,%L,0)',a,
        jsonb_set(request,'{replacement_run_key}',to_jsonb(repeat('3',64)))));
    PERFORM pg_temp.review_must_fail(format('SELECT public.ledger_record_review(%L,%L,0)',a,
        jsonb_set(request,'{replacement_run_key}',to_jsonb(repeat('4',64)))));
    PERFORM pg_temp.review_must_fail(format('SELECT public.ledger_record_review(%L,%L,0)',a,
        jsonb_set(request,'{replacement_run_key}',to_jsonb(repeat('5',64)))));
    PERFORM pg_temp.review_must_fail(format('SELECT public.ledger_record_review(%L,%L,0)',b,request));
    PERFORM pg_temp.review_must_fail(format('SELECT public.ledger_record_review(%L,%L,0)',a,
        request || '{"reason":"untrusted free text"}'));
    PERFORM pg_temp.review_must_fail(format('SELECT public.ledger_record_review(%L,%L,0)',a,
        request || '{"reviewed_at":"2999-01-01T00:00:00Z"}'));
    PERFORM pg_temp.review_must_fail(format('SELECT public.ledger_record_review(%L,%L,0)',a,
        request || '{"decision":"reopen","replacement_run_key":null,"reason_code":"review_reopened"}'));
    first_row := public.ledger_record_review(a,request,0);
    IF public.ledger_record_review(a,request,0) <> first_row THEN RAISE EXCEPTION 'retry changed review'; END IF;
    -- Reverse edge would target an already resolved source and must fail.
    INSERT INTO public.ledger_import_results(account_id,run_key,result,events)
        VALUES(a,repeat('1',64),'{"status":"validated","errors":[]}','[{}]');
    PERFORM pg_temp.review_must_fail(format('SELECT public.ledger_record_review(%L,%L,0)',a,
        request || jsonb_build_object('source_run_key',repeat('2',64),'replacement_run_key',repeat('1',64))));
    request := request || '{"decision":"reopen","replacement_run_key":null,"reason_code":"review_reopened"}';
    PERFORM pg_temp.review_must_fail(format('SELECT public.ledger_record_review(%L,%L,0)',a,request));
    next_row := public.ledger_record_review(a,request,1);
    IF next_row->>'review_key' <> first_row->>'review_key' OR next_row->>'revision' <> '2'
        OR (next_row->>'reviewed_at')::timestamptz <= (first_row->>'reviewed_at')::timestamptz THEN
        RAISE EXCEPTION 'reopen did not append monotonic review';
    END IF;
    IF (SELECT count(*) FROM public.ledger_reviews WHERE account_id=a) <> 2 THEN
        RAISE EXCEPTION 'history lost';
    END IF;
    -- Economic signature matches despite source and quality differences.
    FOR i IN 1..2 LOOP
        INSERT INTO public.ledger_source_records(account_id,source_key,payload_hash,document_hash,row_number)
            VALUES(a,'s'||i,repeat(i::text,64),repeat(i::text,64),1);
        event := jsonb_build_object('account_id',a,'event_key','e'||i,'revision',1,
            'source_type','statement','source_key','s'||i,'source_record_hash',repeat(i::text,64),
            'event_type','deposit','precision','date_only','currency','USD',
            'net_cash_amount',CASE WHEN i=1 THEN '10' ELSE '10.00' END,
            'quality',CASE WHEN i=1 THEN 'verified' ELSE 'provisional' END);
        INSERT INTO public.ledger_events(account_id,event_key,revision,source_key,source_record_hash,payload)
            VALUES(a,'e'||i,1,'s'||i,repeat(i::text,64),event);
    END LOOP;
    duplicate_request := '{"kind":"duplicate_review","left_event_key":"e1","left_revision":1,"right_event_key":"e2","right_revision":1,"decision":"duplicate","reason_code":"same_transaction"}';
    first_row := public.ledger_record_review(a,duplicate_request,0);
    next_row := public.ledger_record_review(a,duplicate_request || '{"decision":"distinct","reason_code":"separate_transactions"}',1);
    IF first_row->>'review_key' <> next_row->>'review_key' OR next_row->>'revision'<>'2' THEN
        RAISE EXCEPTION 'duplicate identity changed';
    END IF;
    event := event || '{"revision":2,"supersedes_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}';
    INSERT INTO public.ledger_events(account_id,event_key,revision,source_key,source_record_hash,payload)
        VALUES(a,'e2',2,'s2',repeat('2',64),event);
    PERFORM pg_temp.review_must_fail(format('SELECT public.ledger_record_review(%L,%L,2)',a,
        duplicate_request || '{"right_revision":99}'));
    -- Stored older revisions remain valid evidence for historical/active projections.
    next_row := public.ledger_record_review(a,duplicate_request,2);
    IF next_row->>'revision'<>'3' THEN RAISE EXCEPTION 'older evidence review rejected'; END IF;
    duplicate_request := duplicate_request || '{"right_revision":2}';
    next_row := public.ledger_record_review(a,duplicate_request,3);
    IF next_row->>'revision'<>'4' OR next_row->>'review_key'<>first_row->>'review_key' THEN
        RAISE EXCEPTION 'changed head did not append same pair';
    END IF;
    IF (SELECT payload->>'net_cash_amount' FROM public.ledger_events
        WHERE account_id=a AND event_key='e2' AND revision=1) <> '10.00' THEN
        RAISE EXCEPTION 'numeric comparison mutated evidence';
    END IF;
    event := event || '{"revision":3,"net_cash_amount":"11.00"}';
    INSERT INTO public.ledger_events(account_id,event_key,revision,source_key,source_record_hash,payload)
        VALUES(a,'e2',3,'s2',repeat('2',64),event);
    PERFORM pg_temp.review_must_fail(format('SELECT public.ledger_record_review(%L,%L,4)',a,
        duplicate_request || '{"right_revision":3}'));
    IF jsonb_array_length(public.ledger_read_review_state(a)->'reviews') <> 6
        OR NOT (public.ledger_read_review_state(a)->'imports'->0 ? 'events')
        OR public.ledger_read_account(a) ? 'reviews' THEN RAISE EXCEPTION 'read contract regression'; END IF;
    PERFORM pg_temp.review_must_fail('UPDATE public.ledger_reviews SET revision=99');
    PERFORM pg_temp.review_must_fail('DELETE FROM public.ledger_reviews');
    PERFORM pg_temp.review_must_fail('TRUNCATE public.ledger_reviews');
END;
$$;
RESET ROLE;
DO $$
DECLARE r text; p text;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF has_function_privilege(r,'public.ledger_record_review(text,jsonb,integer)','EXECUTE')
            OR has_function_privilege(r,'public.ledger_read_review_state(text)','EXECUTE')
            OR has_table_privilege(r,'public.ledger_reviews','SELECT,INSERT,UPDATE,DELETE,TRUNCATE') THEN
            RAISE EXCEPTION 'review privilege leak';
        END IF;
    END LOOP;
    FOREACH p IN ARRAY ARRAY['UPDATE','DELETE','TRUNCATE'] LOOP
        IF has_table_privilege('service_role','public.ledger_reviews',p) THEN RAISE EXCEPTION 'server mutation privilege'; END IF;
    END LOOP;
    IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid='public.ledger_reviews'::regclass) THEN
        RAISE EXCEPTION 'RLS missing';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_proc WHERE oid IN ('public.ledger_record_review(text,jsonb,integer)'::regprocedure,
        'public.ledger_read_review_state(text)'::regprocedure) AND prosecdef) THEN RAISE EXCEPTION 'definer function'; END IF;
    PERFORM pg_temp.review_must_fail('DELETE FROM public.ledger_reviews');
    PERFORM pg_temp.review_must_fail('TRUNCATE public.ledger_reviews');
END;
$$;
ROLLBACK;




