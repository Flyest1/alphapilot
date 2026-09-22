-- Append-only human review decisions. No operating scheduler or execution changes.
BEGIN;
CREATE TABLE public.ledger_reviews (
    account_id text NOT NULL REFERENCES public.ledger_accounts(account_id),
    review_key text NOT NULL CHECK (review_key ~ '^[0-9a-f]{64}$'),
    revision integer NOT NULL CHECK (revision >= 1),
    request jsonb NOT NULL CHECK (jsonb_typeof(request) = 'object'),
    reviewed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (account_id, review_key, revision)
);
ALTER TABLE public.ledger_reviews ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ledger_reviews FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT, INSERT ON public.ledger_reviews TO service_role;
CREATE TRIGGER ledger_append_only BEFORE UPDATE OR DELETE ON public.ledger_reviews
    FOR EACH ROW EXECUTE FUNCTION public.ledger_reject_mutation();
CREATE TRIGGER ledger_no_truncate BEFORE TRUNCATE ON public.ledger_reviews
    FOR EACH STATEMENT EXECUTE FUNCTION public.ledger_reject_mutation();

-- Serialize event head changes against review decisions without UPDATE/LOCK privileges.
CREATE FUNCTION public.ledger_lock_review_account() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended('ledger-review:' || NEW.account_id,0));
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.ledger_lock_review_account() FROM PUBLIC,anon,authenticated;
CREATE TRIGGER ledger_review_head_lock BEFORE INSERT ON public.ledger_events
    FOR EACH ROW EXECUTE FUNCTION public.ledger_lock_review_account();
CREATE FUNCTION public.ledger_record_review(
    p_account_id text, p_request jsonb, p_expected_revision integer
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
    key_value text; key_parts jsonb; latest public.ledger_reviews%ROWTYPE;
    saved public.ledger_reviews%ROWTYPE; source_manifest jsonb; replacement_manifest jsonb;
    replacement_result jsonb; replacement_events jsonb; left_payload jsonb; right_payload jsonb;
    left_document text; right_document text; latest_number integer;
    left_signature jsonb; right_signature jsonb; amount_key text;
    ignored text[] := ARRAY['account_id','event_key','revision','supersedes_hash',
        'source_type','source_key','source_record_hash','observed_at','quality'];
BEGIN
    IF (jsonb_typeof(p_request) = 'object' AND p_expected_revision >= 0) IS NOT TRUE THEN
        RAISE EXCEPTION 'invalid review request';
    END IF;
    IF p_request->>'kind' = 'import_resolution' THEN
        IF (p_request - ARRAY['kind','source_run_key','replacement_run_key','decision','reason_code'] = '{}'
            AND p_request ?& ARRAY['kind','source_run_key','replacement_run_key','decision','reason_code']
            AND jsonb_typeof(p_request->'source_run_key') = 'string'
            AND p_request->>'source_run_key' ~ '^[0-9a-f]{64}$'
            AND ((p_request->>'decision' = 'resolve'
                AND jsonb_typeof(p_request->'replacement_run_key') = 'string'
                AND p_request->>'replacement_run_key' ~ '^[0-9a-f]{64}$'
                AND p_request->>'reason_code' IN ('corrected_mapping','retry_completed'))
                OR (p_request->>'decision' = 'reopen' AND p_request->'replacement_run_key' = 'null'
                AND p_request->>'reason_code' = 'review_reopened'))) IS NOT TRUE THEN
            RAISE EXCEPTION 'invalid import review';
        END IF;
        key_parts := jsonb_build_array('import_resolution',p_request->>'source_run_key');
    ELSIF p_request->>'kind' = 'duplicate_review' THEN
        IF (p_request - ARRAY['kind','left_event_key','left_revision','right_event_key','right_revision','decision','reason_code'] = '{}'
            AND p_request ?& ARRAY['kind','left_event_key','left_revision','right_event_key','right_revision','decision','reason_code']
            AND jsonb_typeof(p_request->'left_event_key') = 'string'
            AND jsonb_typeof(p_request->'right_event_key') = 'string'
            AND (p_request->>'left_event_key') COLLATE "C" < (p_request->>'right_event_key') COLLATE "C"
            AND jsonb_typeof(p_request->'left_revision') = 'number'
            AND jsonb_typeof(p_request->'right_revision') = 'number'
            AND p_request->>'left_revision' ~ '^[1-9][0-9]*$'
            AND p_request->>'right_revision' ~ '^[1-9][0-9]*$'
            AND ((p_request->>'decision' = 'duplicate' AND p_request->>'reason_code' = 'same_transaction')
                OR (p_request->>'decision' = 'distinct' AND p_request->>'reason_code' = 'separate_transactions')
                OR (p_request->>'decision' = 'reopen' AND p_request->>'reason_code' = 'review_reopened'))) IS NOT TRUE THEN
            RAISE EXCEPTION 'invalid duplicate review';
        END IF;
        key_parts := jsonb_build_array('duplicate_review',p_request->>'left_event_key',p_request->>'right_event_key');
    ELSE RAISE EXCEPTION 'unknown review kind'; END IF;
    key_value := encode(sha256(convert_to(key_parts::text,'UTF8')),'hex');
    PERFORM pg_advisory_xact_lock(hashtextextended('ledger-review:' || p_account_id,0));
    SELECT * INTO latest FROM public.ledger_reviews WHERE account_id=p_account_id
        AND review_key=key_value ORDER BY revision DESC LIMIT 1;
    latest_number := COALESCE(latest.revision,0);
    IF latest_number > 0 AND p_expected_revision = latest_number - 1 AND latest.request = p_request THEN
        RETURN to_jsonb(latest);
    END IF;
    IF p_request->>'decision' = 'reopen' AND latest_number = 0 THEN
        RAISE EXCEPTION 'cannot reopen an unreviewed item';
    END IF;
    IF p_expected_revision <> latest_number THEN RAISE EXCEPTION 'review revision conflict'; END IF;
    IF p_request->>'kind' = 'import_resolution' THEN
        SELECT manifest INTO source_manifest FROM public.ledger_import_runs
            WHERE account_id=p_account_id AND run_key=p_request->>'source_run_key';
        IF NOT FOUND THEN RAISE EXCEPTION 'unknown source import'; END IF;
        IF p_request->>'decision' = 'resolve' THEN
            SELECT r.manifest,i.result,i.events INTO replacement_manifest,replacement_result,replacement_events
                FROM public.ledger_import_runs r JOIN public.ledger_import_results i USING(account_id,run_key)
                WHERE r.account_id=p_account_id AND r.run_key=p_request->>'replacement_run_key';
            IF (source_manifest->>'document_hash' = replacement_manifest->>'document_hash'
                AND source_manifest->'source_count' = replacement_manifest->'source_count'
                AND (replacement_manifest->>'source_count')::integer > 0
                AND replacement_result->>'status' = 'validated' AND replacement_result->'errors' = '[]'
                AND jsonb_array_length(replacement_events) = (replacement_manifest->>'source_count')::integer
                AND (replacement_manifest->>'observed_at')::timestamptz >= (source_manifest->>'observed_at')::timestamptz
                AND p_request->>'source_run_key' <> p_request->>'replacement_run_key') IS NOT TRUE THEN
                RAISE EXCEPTION 'replacement must be a complete later import of the same document';
            END IF;
            IF EXISTS (SELECT 1 FROM (SELECT DISTINCT ON (review_key) request
                FROM public.ledger_reviews WHERE account_id=p_account_id ORDER BY review_key,revision DESC) r
                WHERE request->>'kind'='import_resolution' AND request->>'decision'='resolve'
                AND request->>'source_run_key'=p_request->>'replacement_run_key') THEN
                RAISE EXCEPTION 'replacement import is already resolved';
            END IF;
        END IF;
    ELSE
        -- Event insert trigger holds the same account advisory lock.
        SELECT e.payload,s.document_hash INTO left_payload,left_document
            FROM public.ledger_events e JOIN public.ledger_source_records s
            ON s.account_id=e.account_id AND s.source_key=e.source_key AND s.payload_hash=e.source_record_hash
            WHERE e.account_id=p_account_id AND e.event_key=p_request->>'left_event_key'
                AND e.revision=(p_request->>'left_revision')::integer;
        SELECT e.payload,s.document_hash INTO right_payload,right_document
            FROM public.ledger_events e JOIN public.ledger_source_records s
            ON s.account_id=e.account_id AND s.source_key=e.source_key AND s.payload_hash=e.source_record_hash
            WHERE e.account_id=p_account_id AND e.event_key=p_request->>'right_event_key'
                AND e.revision=(p_request->>'right_revision')::integer;
        left_signature := left_payload - ignored;
        right_signature := right_payload - ignored;
        -- Compare decimal values, preserving original immutable evidence strings.
        FOREACH amount_key IN ARRAY ARRAY['quantity','gross_amount','fee','tax','net_cash_amount','counter_amount'] LOOP
            IF left_signature->>amount_key IS NOT NULL THEN
                left_signature := jsonb_set(left_signature,ARRAY[amount_key],
                    to_jsonb(trim_scale((left_signature->>amount_key)::numeric)::text));
            END IF;
            IF right_signature->>amount_key IS NOT NULL THEN
                right_signature := jsonb_set(right_signature,ARRAY[amount_key],
                    to_jsonb(trim_scale((right_signature->>amount_key)::numeric)::text));
            END IF;
        END LOOP;
        IF (left_payload->'revision'=p_request->'left_revision' AND right_payload->'revision'=p_request->'right_revision'
            AND left_document <> right_document AND left_signature = right_signature
            AND left_payload->>'event_type' IN ('trade','deposit','withdrawal','dividend','interest','fx_conversion')
            AND left_payload->>'precision' <> 'aggregate') IS NOT TRUE THEN
            RAISE EXCEPTION 'duplicate review requires matching referenced immutable events from different documents';
        END IF;
    END IF;
    INSERT INTO public.ledger_reviews(account_id,review_key,revision,request,reviewed_at)
        VALUES(p_account_id,key_value,latest_number+1,p_request,
            GREATEST(clock_timestamp(),latest.reviewed_at + interval '1 microsecond')) RETURNING * INTO saved;
    RETURN to_jsonb(saved);
END;
$$;
REVOKE ALL ON FUNCTION public.ledger_record_review(text,jsonb,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ledger_record_review(text,jsonb,integer) TO service_role;
CREATE FUNCTION public.ledger_read_review_state(p_account_id text) RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = '' AS $$
    SELECT jsonb_build_object(
        'events', COALESCE((SELECT jsonb_agg(e.payload ORDER BY e.event_key,e.revision)
            FROM public.ledger_events e WHERE e.account_id=p_account_id),'[]'::jsonb),
        'imports', COALESCE((SELECT jsonb_agg(jsonb_build_object('run_key',r.run_key,
            'manifest',r.manifest,'result',i.result,'events',COALESCE(i.events,'[]'::jsonb)) ORDER BY r.run_key)
            FROM public.ledger_import_runs r LEFT JOIN public.ledger_import_results i USING(account_id,run_key)
            WHERE r.account_id=p_account_id),'[]'::jsonb),
        'reviews', COALESCE((SELECT jsonb_agg(to_jsonb(r) ORDER BY r.review_key,r.revision)
            FROM public.ledger_reviews r WHERE r.account_id=p_account_id),'[]'::jsonb));
$$;
REVOKE ALL ON FUNCTION public.ledger_read_review_state(text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ledger_read_review_state(text) TO service_role;
COMMIT;


