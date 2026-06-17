-- 014: read-only external account sync markers for assets (additive)

alter table assets add column if not exists source text not null default 'manual';
alter table assets add column if not exists external_provider text;
alter table assets add column if not exists external_account_id text;
alter table assets add column if not exists external_asset_key text;
alter table assets add column if not exists synced_at timestamptz;
alter table assets add column if not exists external_payload jsonb not null default '{}'::jsonb;

create unique index if not exists assets_external_source_key_idx
on assets (external_provider, external_account_id, external_asset_key)
where external_provider is not null
  and external_account_id is not null
  and external_asset_key is not null;

create index if not exists assets_source_idx
on assets (source);
