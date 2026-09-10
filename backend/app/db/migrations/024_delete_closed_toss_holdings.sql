-- 024: remove closed positions only for the successfully synchronized Toss account.
-- Replaces 022 without deleting rows at migration time. The next successful sync
-- removes absent/zero positions. strategies.asset_id uses ON DELETE SET NULL;
-- reports, strategies, performance logs, cycles and snapshots remain intact.
-- Keep the existing RPC contract: stale_count now counts deleted asset rows.

create or replace function reconcile_toss_holdings(
  p_account_id text,
  p_synced_at timestamptz,
  p_assets jsonb
)
returns jsonb
language plpgsql
set search_path = public
as $$
declare
  v_created_count integer := 0;
  v_updated_count integer := 0;
  v_stale_count integer := 0;
  v_synced_assets jsonb := '[]'::jsonb;
begin
  if coalesce(btrim(p_account_id), '') = '' then
    raise exception 'Toss account id is required';
  end if;
  if p_synced_at is null then
    raise exception 'Toss synchronization timestamp is required';
  end if;
  if p_assets is null or jsonb_typeof(p_assets) <> 'array' then
    raise exception 'Toss assets must be a JSON array';
  end if;

  if exists (
    select 1
    from jsonb_to_recordset(p_assets) as input_asset(
      market text,
      ticker text,
      external_asset_key text,
      quantity numeric,
      avg_price numeric,
      currency text
    )
    where input_asset.market is null
      or input_asset.market not in ('KR', 'US')
      or coalesce(btrim(input_asset.ticker), '') = ''
      or input_asset.external_asset_key is null
      or input_asset.quantity is null
      or input_asset.quantity < 0
      or input_asset.quantity::text in ('NaN', 'Infinity', '-Infinity')
      or input_asset.avg_price is null
      or input_asset.avg_price < 0
      or input_asset.avg_price::text in ('NaN', 'Infinity', '-Infinity')
      or input_asset.currency is distinct from
        case when input_asset.market = 'KR' then 'KRW' else 'USD' end
      or input_asset.external_asset_key <> input_asset.market || ':' || input_asset.ticker
  ) then
    raise exception 'Toss assets contain invalid holding data';
  end if;

  if (
    select count(*) <> count(distinct input_asset.external_asset_key)
    from jsonb_to_recordset(p_assets) as input_asset(external_asset_key text)
  ) then
    raise exception 'Toss assets contain duplicate external keys';
  end if;

  -- Validate all items (including zero positions) before filtering or mutating.
  select coalesce(jsonb_agg(item), '[]'::jsonb)
  into p_assets
  from jsonb_array_elements(p_assets) as item
  where (item->>'quantity')::numeric > 0;

  select count(*)
  into v_updated_count
  from assets existing_asset
  join jsonb_to_recordset(p_assets) as input_asset(external_asset_key text)
    on input_asset.external_asset_key = existing_asset.external_asset_key
  where existing_asset.external_provider = 'toss_invest'
    and existing_asset.external_account_id = p_account_id;

  v_created_count := jsonb_array_length(p_assets) - v_updated_count;

  insert into assets (
    source,
    external_provider,
    external_account_id,
    external_asset_key,
    market,
    ticker,
    name,
    quantity,
    avg_price,
    currency,
    memo,
    synced_at,
    external_payload
  )
  select
    'toss_api',
    'toss_invest',
    p_account_id,
    input_asset.external_asset_key,
    input_asset.market,
    input_asset.ticker,
    input_asset.name,
    input_asset.quantity,
    input_asset.avg_price,
    input_asset.currency,
    input_asset.memo,
    p_synced_at,
    input_asset.external_payload
  from jsonb_to_recordset(p_assets) as input_asset(
    external_asset_key text,
    market text,
    ticker text,
    name text,
    quantity numeric,
    avg_price numeric,
    currency text,
    memo text,
    external_payload jsonb
  )
  on conflict (external_provider, external_account_id, external_asset_key)
    where external_provider is not null
      and external_account_id is not null
      and external_asset_key is not null
  do update set
    source = excluded.source,
    market = excluded.market,
    ticker = excluded.ticker,
    name = excluded.name,
    quantity = excluded.quantity,
    avg_price = excluded.avg_price,
    currency = excluded.currency,
    memo = excluded.memo,
    synced_at = excluded.synced_at,
    external_payload = excluded.external_payload,
    updated_at = now();

  with stale_assets as (
    delete from assets existing_asset
    where existing_asset.source = 'toss_api'
      and existing_asset.external_provider = 'toss_invest'
      and existing_asset.external_account_id = p_account_id
      and not exists (
        select 1
        from jsonb_to_recordset(p_assets) as input_asset(external_asset_key text)
        where input_asset.external_asset_key = existing_asset.external_asset_key
      )
    returning 1
  )
  select count(*) into v_stale_count from stale_assets;

  select coalesce(jsonb_agg(to_jsonb(existing_asset) order by existing_asset.created_at), '[]'::jsonb)
  into v_synced_assets
  from assets existing_asset
  where existing_asset.external_provider = 'toss_invest'
    and existing_asset.external_account_id = p_account_id
    and exists (
      select 1
      from jsonb_to_recordset(p_assets) as input_asset(external_asset_key text)
      where input_asset.external_asset_key = existing_asset.external_asset_key
    );

  return jsonb_build_object(
    'assets', v_synced_assets,
    'created_count', v_created_count,
    'updated_count', v_updated_count,
    'stale_count', v_stale_count
  );
end;
$$;

revoke all on function reconcile_toss_holdings(text, timestamptz, jsonb) from public;
revoke all on function reconcile_toss_holdings(text, timestamptz, jsonb) from anon;
revoke all on function reconcile_toss_holdings(text, timestamptz, jsonb) from authenticated;
grant execute on function reconcile_toss_holdings(text, timestamptz, jsonb) to service_role;
