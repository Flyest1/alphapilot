create table if not exists assets (
  id uuid primary key default gen_random_uuid(),
  market text not null,
  ticker text not null,
  name text not null,
  quantity numeric not null,
  avg_price numeric not null,
  currency text default 'KRW',
  memo text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

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

create table if not exists reports (
  id uuid primary key default gen_random_uuid(),
  report_type text not null,
  title text not null,
  summary text,
  content jsonb not null,
  created_at timestamptz default now()
);

create table if not exists strategies (
  id uuid primary key default gen_random_uuid(),
  report_id uuid references reports(id) on delete cascade,
  asset_id uuid references assets(id) on delete set null,
  ticker text not null,
  name text,
  action text not null,
  confidence numeric,
  current_price numeric,
  buy_range_low numeric,
  buy_range_high numeric,
  sell_range_low numeric,
  sell_range_high numeric,
  target_price numeric,
  stop_loss numeric,
  reasoning text,
  risk text,
  invalidation_condition text,
  created_at timestamptz default now()
);

create table if not exists settings (
  id uuid primary key default gen_random_uuid(),
  domestic_report_time text default '08:30',
  global_report_time text default '22:30',
  ai_provider text default 'openai',
  ai_model text default 'gpt-5.4-mini',
  risk_profile text default 'balanced',
  candidate_horizon text default 'medium',
  frontend_timezone text default 'Asia/Seoul',
  stale_data_business_days int default 2,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists performance_logs (
  id uuid primary key default gen_random_uuid(),
  strategy_id uuid references strategies(id) on delete cascade,
  ticker text not null,
  action text not null,
  price_at_recommendation numeric,
  price_after_1d numeric,
  price_after_5d numeric,
  price_after_20d numeric,
  return_after_1d numeric,
  return_after_5d numeric,
  return_after_20d numeric,
  evaluated_at timestamptz,
  created_at timestamptz default now()
);
