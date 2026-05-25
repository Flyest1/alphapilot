create table if not exists candidate_assets (
  id uuid primary key default gen_random_uuid(),
  market text not null,
  ticker text not null,
  name text not null,
  currency text default 'KRW',
  memo text,
  is_active boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
