-- 016: Immutable signal-model lineage and read-only shadow-evaluation audit foundation.
-- Exactly one champion is seeded. No challenger or evaluation run is created here.

create table if not exists signal_model_versions (
  id uuid primary key default gen_random_uuid(),
  model_key text not null,
  version text not null,
  config jsonb not null,
  config_sha256 text not null,
  metadata jsonb not null default
    '{"research_only": true, "adoption_permitted": false, "evaluation_window_weeks": 12}'::jsonb,
  created_at timestamptz not null default now(),
  unique (model_key, version),
  unique (config_sha256),
  check (config_sha256 ~ '^[0-9a-f]{64}$'),
  check (jsonb_typeof(config) = 'object'),
  check (jsonb_typeof(metadata) = 'object')
);

create or replace function prevent_signal_model_version_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'signal_model_versions are immutable';
end;
$$;

drop trigger if exists signal_model_versions_immutable on signal_model_versions;
create trigger signal_model_versions_immutable
before update or delete on signal_model_versions
for each row execute function prevent_signal_model_version_mutation();

create table if not exists signal_model_assignments (
  id uuid primary key default gen_random_uuid(),
  model_version_id uuid not null references signal_model_versions(id) on delete restrict,
  role text not null check (role in ('champion', 'challenger')),
  effective_at timestamptz not null default now(),
  ended_at timestamptz,
  assignment_reason text not null default 'manual_review',
  metadata jsonb not null default
    '{"research_only": true, "automatic_promotion": false}'::jsonb,
  created_at timestamptz not null default now(),
  check (ended_at is null or ended_at >= effective_at),
  check (jsonb_typeof(metadata) = 'object')
);

create unique index if not exists signal_model_assignments_active_role_idx
on signal_model_assignments (role)
where ended_at is null;

create index if not exists signal_model_assignments_role_effective_at_idx
on signal_model_assignments (role, effective_at desc);

create table if not exists signal_model_evaluation_runs (
  id uuid primary key default gen_random_uuid(),
  champion_model_version_id uuid not null references signal_model_versions(id) on delete restrict,
  challenger_model_version_id uuid not null references signal_model_versions(id) on delete restrict,
  champion_config_sha256 text not null,
  challenger_config_sha256 text not null,
  report_type text not null,
  trigger_type text not null check (trigger_type = 'scheduled'),
  decision_at timestamptz not null,
  started_at timestamptz not null,
  ends_at timestamptz not null,
  evaluation_window_weeks smallint not null default 12 check (evaluation_window_weeks = 12),
  status text not null default 'pending'
    check (status in ('pending', 'collecting', 'review_ready', 'failed')),
  failure_reason text,
  duration_seconds numeric,
  expected_observation_count integer not null default 0 check (expected_observation_count >= 0),
  observed_observation_count integer not null default 0 check (observed_observation_count >= 0),
  excluded_observation_count integer not null default 0 check (excluded_observation_count >= 0),
  input_snapshot jsonb not null,
  input_sha256 text not null,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  check (champion_model_version_id <> challenger_model_version_id),
  check (champion_config_sha256 <> challenger_config_sha256),
  check (champion_config_sha256 ~ '^[0-9a-f]{64}$'),
  check (challenger_config_sha256 ~ '^[0-9a-f]{64}$'),
  check (input_sha256 ~ '^[0-9a-f]{64}$'),
  check (ends_at = started_at + interval '12 weeks'),
  check (completed_at is null or completed_at >= started_at),
  check (status <> 'review_ready' or completed_at >= ends_at),
  check (
    (status = 'failed' and failure_reason is not null)
    or (status <> 'failed' and failure_reason is null)
  ),
  check (jsonb_typeof(input_snapshot) = 'object')
);

create or replace function validate_signal_model_evaluation_run()
returns trigger
language plpgsql
as $$
declare
  stored_champion_sha256 text;
  stored_challenger_sha256 text;
begin
  if new.status = 'review_ready' and now() < new.ends_at then
    raise exception 'evaluation cannot be review-ready before the 12-week window ends';
  end if;

  select config_sha256 into stored_champion_sha256
  from signal_model_versions
  where id = new.champion_model_version_id;

  select config_sha256 into stored_challenger_sha256
  from signal_model_versions
  where id = new.challenger_model_version_id;

  if stored_champion_sha256 is null
    or stored_challenger_sha256 is null
    or stored_champion_sha256 <> new.champion_config_sha256
    or stored_challenger_sha256 <> new.challenger_config_sha256 then
    raise exception 'evaluation run config hashes do not match model versions';
  end if;

  return new;
end;
$$;

drop trigger if exists signal_model_evaluation_run_hash_check on signal_model_evaluation_runs;
create trigger signal_model_evaluation_run_hash_check
before insert or update on signal_model_evaluation_runs
for each row execute function validate_signal_model_evaluation_run();

create index if not exists signal_model_evaluation_runs_created_at_idx
on signal_model_evaluation_runs (created_at desc);

create table if not exists signal_model_evaluation_observations (
  id uuid primary key default gen_random_uuid(),
  evaluation_run_id uuid not null references signal_model_evaluation_runs(id) on delete cascade,
  model_version_id uuid not null references signal_model_versions(id) on delete restrict,
  arm text not null check (arm in ('champion', 'challenger')),
  observation_key text not null,
  observed_at timestamptz not null,
  market text not null,
  ticker text not null,
  action text not null,
  horizon text not null,
  reference_price numeric,
  target_price numeric,
  stop_loss numeric,
  outcome_status text not null default 'pending',
  returns jsonb not null default '{}'::jsonb,
  outcome_snapshot jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (evaluation_run_id, arm, observation_key),
  check (jsonb_typeof(returns) = 'object'),
  check (jsonb_typeof(outcome_snapshot) = 'object')
);

create or replace function validate_signal_model_evaluation_observation()
returns trigger
language plpgsql
as $$
declare
  expected_model_version_id uuid;
begin
  select case
    when new.arm = 'champion' then champion_model_version_id
    else challenger_model_version_id
  end
  into expected_model_version_id
  from signal_model_evaluation_runs
  where id = new.evaluation_run_id;

  if expected_model_version_id is null or new.model_version_id <> expected_model_version_id then
    raise exception 'evaluation observation model_version_id does not match its arm';
  end if;

  return new;
end;
$$;

drop trigger if exists signal_model_evaluation_observation_arm_check on signal_model_evaluation_observations;
create trigger signal_model_evaluation_observation_arm_check
before insert or update on signal_model_evaluation_observations
for each row execute function validate_signal_model_evaluation_observation();

create index if not exists signal_model_evaluation_observations_run_arm_observed_at_idx
on signal_model_evaluation_observations (evaluation_run_id, arm, observed_at);

create table if not exists signal_model_report_links (
  report_id uuid primary key references reports(id) on delete restrict,
  generation_source text not null check (generation_source in ('scheduled', 'manual')),
  is_official_sample boolean not null,
  champion_assignment_id uuid not null references signal_model_assignments(id) on delete restrict,
  champion_version_id uuid not null references signal_model_versions(id) on delete restrict,
  report_inputs_snapshot jsonb not null,
  input_sha256 text not null,
  evaluation_id uuid references signal_model_evaluation_runs(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((generation_source = 'scheduled') = is_official_sample),
  check (generation_source <> 'manual' or evaluation_id is null),
  check (input_sha256 ~ '^[0-9a-f]{64}$'),
  check (jsonb_typeof(report_inputs_snapshot) = 'object')
);

create or replace function validate_signal_model_report_link()
returns trigger
language plpgsql
as $$
declare
  assigned_version_id uuid;
  assigned_role text;
  assigned_effective_at timestamptz;
  assigned_ended_at timestamptz;
begin
  select model_version_id, role, effective_at, ended_at
  into assigned_version_id, assigned_role, assigned_effective_at, assigned_ended_at
  from signal_model_assignments
  where id = new.champion_assignment_id;

  if assigned_role <> 'champion' or assigned_version_id <> new.champion_version_id then
    raise exception 'report link champion assignment does not match its model version';
  end if;
  if new.created_at < assigned_effective_at
    or (assigned_ended_at is not null and new.created_at > assigned_ended_at) then
    raise exception 'report link champion assignment was not active at capture time';
  end if;

  return new;
end;
$$;

drop trigger if exists signal_model_report_link_assignment_check on signal_model_report_links;
create trigger signal_model_report_link_assignment_check
before insert or update on signal_model_report_links
for each row execute function validate_signal_model_report_link();

create index if not exists signal_model_report_links_source_created_at_idx
on signal_model_report_links (generation_source, created_at desc);

insert into signal_model_versions (model_key, version, config, config_sha256, metadata)
values (
  'technical_score',
  'v1',
  '{"score_version":"technical_score_v1","technical_score_weights":{"momentum":25,"price_position":15,"trend":30,"volatility":15,"volume":15}}'::jsonb,
  'f659f694f5c8e4e66f2cd9d98dadc44901cd611fd6ab315e26e48a4802053f26',
  '{"research_only":true,"adoption_permitted":false,"evaluation_window_weeks":12}'::jsonb
)
on conflict (model_key, version) do nothing;

do $$
begin
  if not exists (
    select 1
    from signal_model_versions
    where model_key = 'technical_score'
      and version = 'v1'
      and config = '{"score_version":"technical_score_v1","technical_score_weights":{"momentum":25,"price_position":15,"trend":30,"volatility":15,"volume":15}}'::jsonb
      and config_sha256 = 'f659f694f5c8e4e66f2cd9d98dadc44901cd611fd6ab315e26e48a4802053f26'
  ) then
    raise exception 'existing technical_score/v1 does not match the immutable baseline';
  end if;
end;
$$;

insert into signal_model_assignments (model_version_id, role, assignment_reason, metadata)
select
  id,
  'champion',
  'initial_immutable_baseline',
  '{"research_only":true,"automatic_promotion":false}'::jsonb
from signal_model_versions
where model_key = 'technical_score'
  and version = 'v1'
  and not exists (
    select 1 from signal_model_assignments where role = 'champion' and ended_at is null
  );
