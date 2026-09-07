-- 023: keep scheduled and manual report jobs distinct during active-job deduplication

alter table report_jobs
add column if not exists generation_source text not null default 'manual';

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'report_jobs_generation_source_check'
      and conrelid = 'report_jobs'::regclass
  ) then
    alter table report_jobs
    add constraint report_jobs_generation_source_check
    check (generation_source in ('scheduled', 'manual'));
  end if;
end;
$$;

create index if not exists report_jobs_type_source_status_idx
on report_jobs (report_type, generation_source, status, created_at desc);
