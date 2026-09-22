-- Local/offline ledger storage only. Apply manually after review; no operating tables touched.
-- Decimal payload strings remain intact; unconstrained numeric avoids silent typmod rounding.
BEGIN;
CREATE TABLE public.ledger_accounts (
    account_id text PRIMARY KEY CHECK (length(account_id) BETWEEN 1 AND 200 AND account_id !~ '^\s|\s$'),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.ledger_import_runs (
    account_id text NOT NULL REFERENCES public.ledger_accounts(account_id),
    run_key text NOT NULL CHECK (run_key ~ '^[0-9a-f]{64}$'),
    manifest jsonb NOT NULL CHECK (jsonb_typeof(manifest) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, run_key)
);
CREATE TABLE public.ledger_source_records (
    account_id text NOT NULL REFERENCES public.ledger_accounts(account_id),
    source_key text NOT NULL CHECK (length(source_key) BETWEEN 1 AND 200 AND source_key !~ '^\s|\s$'),
    payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    document_hash text NOT NULL CHECK (document_hash ~ '^[0-9a-f]{64}$'),
    row_number integer NOT NULL CHECK (row_number >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, source_key, payload_hash)
);
CREATE TABLE public.ledger_import_sources (
    account_id text NOT NULL,
    run_key text NOT NULL,
    source_key text NOT NULL,
    payload_hash text NOT NULL,
    PRIMARY KEY (account_id, run_key, source_key, payload_hash),
    FOREIGN KEY (account_id, run_key) REFERENCES public.ledger_import_runs(account_id, run_key),
    FOREIGN KEY (account_id, source_key, payload_hash)
        REFERENCES public.ledger_source_records(account_id, source_key, payload_hash)
);
CREATE TABLE public.ledger_events (
    account_id text NOT NULL,
    event_key text NOT NULL CHECK (length(event_key) BETWEEN 1 AND 200 AND event_key !~ '^\s|\s$'),
    revision integer NOT NULL CHECK (revision >= 1),
    source_key text NOT NULL,
    source_record_hash text NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, event_key, revision),
    FOREIGN KEY (account_id, source_key, source_record_hash)
        REFERENCES public.ledger_source_records(account_id, source_key, payload_hash),
    CHECK ((payload->>'account_id' = account_id AND payload->>'event_key' = event_key
        AND payload->>'source_key' = source_key AND payload->>'source_record_hash' = source_record_hash
        AND payload->'revision' = to_jsonb(revision) AND payload->>'source_type' = 'statement') IS TRUE)
);
CREATE TABLE public.ledger_import_results (
    events jsonb NOT NULL CHECK (jsonb_typeof(events) = 'array'),
    account_id text NOT NULL,
    run_key text NOT NULL,
    result jsonb NOT NULL CHECK (jsonb_typeof(result) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, run_key),
    FOREIGN KEY (account_id, run_key) REFERENCES public.ledger_import_runs(account_id, run_key)
);
CREATE TABLE public.ledger_reconciliation_runs (
    account_id text NOT NULL REFERENCES public.ledger_accounts(account_id),
    run_key text NOT NULL CHECK (run_key ~ '^[0-9a-f]{64}$'),
    input jsonb NOT NULL CHECK (jsonb_typeof(input) = 'object'),
    result jsonb NOT NULL CHECK (jsonb_typeof(result) = 'object'),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, run_key)
);
CREATE TABLE public.ledger_postings (
    account_id text NOT NULL,
    run_key text NOT NULL,
    journal_index integer NOT NULL CHECK (journal_index >= 0),
    leg_index integer NOT NULL CHECK (leg_index >= 0),
    currency text NOT NULL CHECK (currency IN ('KRW', 'USD')),
    book_account text NOT NULL CHECK (book_account IN ('cash', 'receivables', 'payables',
        'fees', 'taxes', 'security_notional_clearing', 'external_capital', 'income', 'fx_clearing')),
    amount numeric NOT NULL CHECK (abs(amount) < 1e26 AND scale(amount) <= 12),
    PRIMARY KEY (account_id, run_key, journal_index, leg_index),
    FOREIGN KEY (account_id, run_key) REFERENCES public.ledger_reconciliation_runs(account_id, run_key)
);

CREATE FUNCTION public.ledger_reject_mutation() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
    RAISE EXCEPTION 'ledger rows are append-only';
END;
$$;
REVOKE ALL ON FUNCTION public.ledger_reject_mutation() FROM PUBLIC, anon, authenticated;
DO $$
DECLARE table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['ledger_accounts', 'ledger_import_runs',
        'ledger_source_records', 'ledger_import_sources', 'ledger_events',
        'ledger_import_results', 'ledger_reconciliation_runs', 'ledger_postings'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC, anon, authenticated, service_role', table_name);
        EXECUTE format('GRANT SELECT, INSERT ON TABLE public.%I TO service_role', table_name);
        EXECUTE format('CREATE TRIGGER ledger_append_only BEFORE UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.ledger_reject_mutation()', table_name);
        EXECUTE format('CREATE TRIGGER ledger_no_truncate BEFORE TRUNCATE ON public.%I '
            'FOR EACH STATEMENT EXECUTE FUNCTION public.ledger_reject_mutation()', table_name);
    END LOOP;
END;
$$;

CREATE FUNCTION public.ledger_capture_import(
    p_account_id text, p_run_key text, p_manifest jsonb, p_sources jsonb
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE item jsonb; stored jsonb; source_row public.ledger_source_records%ROWTYPE;
BEGIN
    IF (jsonb_typeof(p_manifest) = 'object' AND jsonb_typeof(p_sources) = 'array'
        AND p_manifest->>'document_hash' ~ '^[0-9a-f]{64}$'
        AND p_manifest->>'mapping_hash' ~ '^[0-9a-f]{64}$'
        AND jsonb_typeof(p_manifest->'schema_version') = 'string'
        AND jsonb_typeof(p_manifest->'observed_at') = 'string'
        AND p_manifest->>'source_type' = 'statement'
        AND p_manifest->'source_count' = to_jsonb(jsonb_array_length(p_sources))
        AND p_manifest->'coverage_verified' = 'false'::jsonb) IS NOT TRUE THEN
        RAISE EXCEPTION 'invalid ledger import manifest';
    END IF;
    INSERT INTO public.ledger_accounts(account_id) VALUES (p_account_id) ON CONFLICT DO NOTHING;
    INSERT INTO public.ledger_import_runs(account_id, run_key, manifest)
        VALUES (p_account_id, p_run_key, p_manifest) ON CONFLICT DO NOTHING;
    SELECT manifest INTO stored FROM public.ledger_import_runs
        WHERE account_id = p_account_id AND run_key = p_run_key;
    IF stored IS DISTINCT FROM p_manifest THEN RAISE EXCEPTION 'conflicting import manifest'; END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(p_sources) LOOP
        IF (jsonb_typeof(item) = 'object'
            AND item - ARRAY['source_key','payload_hash','document_hash','row_number'] = '{}'::jsonb
            AND jsonb_typeof(item->'source_key') = 'string'
            AND jsonb_typeof(item->'payload_hash') = 'string'
            AND jsonb_typeof(item->'document_hash') = 'string'
            AND item->>'document_hash' = p_manifest->>'document_hash'
            AND jsonb_typeof(item->'row_number') = 'number'
            AND item->>'row_number' ~ '^[1-9][0-9]*$') IS NOT TRUE THEN
            RAISE EXCEPTION 'invalid ledger source metadata';
        END IF;
        INSERT INTO public.ledger_source_records(account_id, source_key, payload_hash, document_hash, row_number)
            VALUES (p_account_id, item->>'source_key', item->>'payload_hash',
                item->>'document_hash', (item->>'row_number')::integer) ON CONFLICT DO NOTHING;
        SELECT * INTO source_row FROM public.ledger_source_records WHERE account_id = p_account_id
            AND source_key = item->>'source_key' AND payload_hash = item->>'payload_hash';
        IF source_row.document_hash IS DISTINCT FROM item->>'document_hash'
            OR source_row.row_number IS DISTINCT FROM (item->>'row_number')::integer THEN
            RAISE EXCEPTION 'conflicting source metadata';
        END IF;
        INSERT INTO public.ledger_import_sources(account_id, run_key, source_key, payload_hash)
            VALUES (p_account_id, p_run_key, item->>'source_key', item->>'payload_hash') ON CONFLICT DO NOTHING;
    END LOOP;
    IF (SELECT count(*) FROM public.ledger_import_sources WHERE account_id = p_account_id
        AND run_key = p_run_key) <> jsonb_array_length(p_sources) THEN
        RAISE EXCEPTION 'source set differs or contains duplicates';
    END IF;
    RETURN jsonb_build_object('run_key', p_run_key);
END;
$$;

CREATE FUNCTION public.ledger_publish_import(
    p_account_id text, p_run_key text, p_events jsonb, p_result jsonb
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE item jsonb; stored jsonb; stored_events jsonb; amount_key text;
BEGIN
    IF (jsonb_typeof(p_events) = 'array' AND jsonb_typeof(p_result) = 'object'
        AND p_result->>'status' IN ('validated','partial','rejected')
        AND jsonb_typeof(p_result->'errors') = 'array'
        AND p_result->'coverage_verified' = 'false'::jsonb) IS NOT TRUE THEN
        RAISE EXCEPTION 'invalid import result';
    END IF;
    -- Serializes publication of the same run without requiring UPDATE privileges.
    PERFORM pg_advisory_xact_lock(hashtextextended(p_account_id || ':' || p_run_key, 0));
    IF NOT EXISTS (SELECT 1 FROM public.ledger_import_runs
        WHERE account_id = p_account_id AND run_key = p_run_key) THEN
        RAISE EXCEPTION 'unknown import run';
    END IF;
    SELECT result, events INTO stored, stored_events FROM public.ledger_import_results
        WHERE account_id = p_account_id AND run_key = p_run_key;
    IF FOUND AND (stored IS DISTINCT FROM p_result OR stored_events IS DISTINCT FROM p_events) THEN
        RAISE EXCEPTION 'conflicting import result or event set';
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(p_events) LOOP
        IF (jsonb_typeof(item) = 'object' AND jsonb_typeof(item->'account_id') = 'string'
            AND item->>'account_id' = p_account_id AND item->>'source_type' = 'statement'
            AND jsonb_typeof(item->'event_key') = 'string'
            AND jsonb_typeof(item->'source_key') = 'string'
            AND jsonb_typeof(item->'source_record_hash') = 'string'
            AND jsonb_typeof(item->'revision') = 'number'
            AND item->>'revision' ~ '^[1-9][0-9]*$'
            AND item->>'quality' IN ('verified','provisional','quarantined')) IS NOT TRUE THEN
            RAISE EXCEPTION 'invalid event identity';
        END IF;
        FOREACH amount_key IN ARRAY ARRAY['quantity','gross_amount','fee','tax','net_cash_amount','counter_amount'] LOOP
            IF item ? amount_key AND item->amount_key <> 'null'::jsonb THEN
                IF jsonb_typeof(item->amount_key) <> 'string'
                    OR item->>amount_key !~ '^-?[0-9]+(\.[0-9]{1,12})?$' THEN
                    RAISE EXCEPTION 'invalid decimal string';
                END IF;
                IF abs((item->>amount_key)::numeric) >= 1e26 THEN RAISE EXCEPTION 'decimal overflow'; END IF;
            END IF;
        END LOOP;
        IF NOT EXISTS (SELECT 1 FROM public.ledger_import_sources WHERE account_id = p_account_id
            AND run_key = p_run_key AND source_key = item->>'source_key'
            AND payload_hash = item->>'source_record_hash') THEN
            RAISE EXCEPTION 'event source is not in this account import';
        END IF;
        INSERT INTO public.ledger_events(account_id,event_key,revision,source_key,source_record_hash,payload)
            VALUES (p_account_id,item->>'event_key',(item->>'revision')::integer,
                item->>'source_key',item->>'source_record_hash',item) ON CONFLICT DO NOTHING;
        SELECT payload INTO stored FROM public.ledger_events WHERE account_id = p_account_id
            AND event_key = item->>'event_key' AND revision = (item->>'revision')::integer;
        -- Re-observation is evidence receipt, not a new economic event or revision.
        -- Keep the first persisted observation immutable. An earlier timestamp cannot
        -- silently rewrite historical knowledge already used by saved reconciliations.
        IF (stored - 'observed_at') IS DISTINCT FROM (item - 'observed_at') THEN
            RAISE EXCEPTION 'conflicting event revision';
        END IF;
        IF (jsonb_typeof(item->'observed_at') = 'string'
            AND jsonb_typeof(stored->'observed_at') = 'string'
            AND (item->>'observed_at')::timestamptz >= (stored->>'observed_at')::timestamptz) IS NOT TRUE THEN
            RAISE EXCEPTION 'earlier or invalid event observation';
        END IF;
    END LOOP;
    INSERT INTO public.ledger_import_results(account_id,run_key,result,events)
        VALUES (p_account_id,p_run_key,p_result,p_events) ON CONFLICT DO NOTHING;
    RETURN jsonb_build_object('run_key',p_run_key,'event_count',jsonb_array_length(p_events));
END;
$$;

CREATE FUNCTION public.ledger_save_reconciliation(
    p_account_id text, p_run_key text, p_input jsonb, p_result jsonb
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE stored public.ledger_reconciliation_runs%ROWTYPE; journal jsonb; leg jsonb;
    journal_number integer := 0; leg_number integer; total numeric; parsed numeric;
BEGIN
    IF (jsonb_typeof(p_input) = 'object' AND jsonb_typeof(p_result) = 'object'
        AND p_input->'opening'->>'account_id' = p_account_id
        AND p_result->'replay'->>'account_id' = p_account_id
        AND p_result->'replay'->'coverage_verified' = 'false'::jsonb
        AND p_result->'replay'->'return_rate' = 'null'::jsonb
        AND jsonb_typeof(p_result->'replay'->'journals') = 'array'
        AND (p_result->'reconciliation' = 'null'::jsonb OR (
            p_result->'reconciliation'->'coverage_verified' = 'false'::jsonb
            AND p_result->'reconciliation'->'return_rate' = 'null'::jsonb))) IS NOT TRUE THEN
        RAISE EXCEPTION 'invalid reconciliation context';
    END IF;
    IF p_input->'observed' IS NOT NULL AND p_input->'observed' <> 'null'::jsonb
        AND (p_input->'observed'->>'account_id' = p_account_id) IS NOT TRUE THEN
        RAISE EXCEPTION 'observation account mismatch';
    END IF;
    INSERT INTO public.ledger_reconciliation_runs(account_id,run_key,input,result)
        VALUES (p_account_id,p_run_key,p_input,p_result) ON CONFLICT DO NOTHING;
    SELECT * INTO stored FROM public.ledger_reconciliation_runs
        WHERE account_id = p_account_id AND run_key = p_run_key;
    IF stored.input IS DISTINCT FROM p_input OR stored.result IS DISTINCT FROM p_result THEN
        RAISE EXCEPTION 'conflicting reconciliation';
    END IF;
    FOR journal IN SELECT value FROM jsonb_array_elements(p_result->'replay'->'journals') LOOP
        IF (jsonb_typeof(journal->'legs') = 'array'
            AND journal->>'currency' IN ('KRW','USD')
            AND jsonb_typeof(journal->'revision') = 'number'
            AND journal->>'revision' ~ '^[1-9][0-9]*$') IS NOT TRUE THEN
            RAISE EXCEPTION 'invalid journal';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM public.ledger_events WHERE account_id = p_account_id
            AND event_key = journal->>'event_key' AND revision = (journal->>'revision')::integer
            AND source_record_hash = journal->>'evidence_hash' AND payload->>'quality' = 'verified'
            AND payload->>'event_type' <> 'execution_aggregate' AND payload->>'precision' <> 'aggregate') THEN
            RAISE EXCEPTION 'journal requires verified event evidence';
        END IF;
        total := 0; leg_number := 0;
        FOR leg IN SELECT value FROM jsonb_array_elements(journal->'legs') LOOP
            IF (jsonb_typeof(leg->'amount') = 'string'
                AND leg->>'amount' ~ '^-?[0-9]+(\.[0-9]{1,12})?$'
                AND leg->>'currency' = journal->>'currency') IS NOT TRUE THEN
                RAISE EXCEPTION 'invalid journal decimal or currency';
            END IF;
            parsed := (leg->>'amount')::numeric;
            IF abs(parsed) >= 1e26 THEN RAISE EXCEPTION 'posting overflow'; END IF;
            total := total + parsed;
            INSERT INTO public.ledger_postings(account_id,run_key,journal_index,leg_index,currency,book_account,amount)
                VALUES (p_account_id,p_run_key,journal_number,leg_number,leg->>'currency',leg->>'account',parsed)
                ON CONFLICT DO NOTHING;
            leg_number := leg_number + 1;
        END LOOP;
        IF total <> 0 OR leg_number = 0 THEN RAISE EXCEPTION 'unbalanced or empty journal'; END IF;
        journal_number := journal_number + 1;
    END LOOP;
    RETURN jsonb_build_object('run_key',p_run_key,'journal_count',journal_number);
END;
$$;
REVOKE ALL ON FUNCTION public.ledger_capture_import(text,text,jsonb,jsonb) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.ledger_publish_import(text,text,jsonb,jsonb) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.ledger_save_reconciliation(text,text,jsonb,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ledger_capture_import(text,text,jsonb,jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.ledger_publish_import(text,text,jsonb,jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.ledger_save_reconciliation(text,text,jsonb,jsonb) TO service_role;
CREATE FUNCTION public.ledger_read_account(p_account_id text) RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
    SELECT jsonb_build_object(
        'events', COALESCE((SELECT jsonb_agg(e.payload ORDER BY e.event_key, e.revision)
            FROM public.ledger_events e WHERE e.account_id = p_account_id), '[]'::jsonb),
        'imports', COALESCE((SELECT jsonb_agg(jsonb_build_object(
            'run_key', r.run_key, 'manifest', r.manifest, 'result', i.result) ORDER BY r.run_key)
            FROM public.ledger_import_runs r LEFT JOIN public.ledger_import_results i
            ON i.account_id = r.account_id AND i.run_key = r.run_key
            WHERE r.account_id = p_account_id), '[]'::jsonb)
    );
$$;
REVOKE ALL ON FUNCTION public.ledger_read_account(text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ledger_read_account(text) TO service_role;
COMMIT;
