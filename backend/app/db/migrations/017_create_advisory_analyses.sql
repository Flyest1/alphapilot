create table if not exists advisory_jobs (
  job_id uuid primary key default gen_random_uuid(),
  analysis_type text not null check (
    analysis_type in (
      'undervalued_us_stocks',
      'etf_rebalancing',
      'post_earnings_opportunities',
      'ai_beneficiaries',
      'high_dividend_etfs',
      'sec_filing_risk',
      'etf_overlap',
      'sector_outlook'
    )
  ),
  request_payload jsonb not null,
  request_hash text not null check (request_hash ~ '^[0-9a-f]{64}$'),
  status text not null default 'queued' check (status in ('queued', 'running', 'completed', 'failed')),
  analysis_id uuid,
  step_timings jsonb not null default '{}'::jsonb,
  error_code text,
  message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (jsonb_typeof(request_payload) = 'object'),
  check (jsonb_typeof(step_timings) = 'object'),
  check (
    (status = 'completed' and analysis_id is not null and completed_at is not null)
    or (status <> 'completed')
  )
);

create table if not exists advisory_analyses (
  analysis_id uuid primary key default gen_random_uuid(),
  job_id uuid not null unique references advisory_jobs(job_id) on delete restrict,
  analysis_type text not null check (
    analysis_type in (
      'undervalued_us_stocks',
      'etf_rebalancing',
      'post_earnings_opportunities',
      'ai_beneficiaries',
      'high_dividend_etfs',
      'sec_filing_risk',
      'etf_overlap',
      'sector_outlook'
    )
  ),
  request_hash text not null check (request_hash ~ '^[0-9a-f]{64}$'),
  request_payload jsonb not null,
  result_payload jsonb not null,
  created_at timestamptz not null default now(),
  check (jsonb_typeof(request_payload) = 'object'),
  check (jsonb_typeof(result_payload) = 'object')
);

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'advisory_jobs_analysis_id_fkey'
  ) then
    alter table advisory_jobs
      add constraint advisory_jobs_analysis_id_fkey
      foreign key (analysis_id) references advisory_analyses(analysis_id) on delete restrict;
  end if;
end;
$$;

create unique index if not exists advisory_jobs_active_request_hash_idx
on advisory_jobs (request_hash)
where status in ('queued', 'running');

create index if not exists advisory_jobs_status_created_at_idx
on advisory_jobs (status, created_at desc);

create index if not exists advisory_analyses_type_created_at_idx
on advisory_analyses (analysis_type, created_at desc);
