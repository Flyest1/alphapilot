create table if not exists report_jobs (
  job_id uuid primary key default gen_random_uuid(),
  report_type text not null,
  status text not null default 'queued',
  report_id uuid references reports(id) on delete set null,
  message text,
  error_category text,
  step_timings jsonb not null default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists report_jobs_report_type_status_idx
on report_jobs (report_type, status, created_at desc);
