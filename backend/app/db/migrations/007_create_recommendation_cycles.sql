create table if not exists recommendation_cycles (
  id uuid primary key default gen_random_uuid(),
  strategy_id uuid references strategies(id) on delete set null,
  report_id uuid references reports(id) on delete set null,
  report_type text not null,
  ticker text not null,
  name text,
  action text not null,
  horizon text not null default 'medium',
  status text not null default 'active',
  started_at timestamptz default now(),
  closed_at timestamptz,
  reference_price numeric,
  target_price numeric,
  stop_loss numeric,
  price_after_1d numeric,
  price_after_5d numeric,
  price_after_20d numeric,
  price_after_60d numeric,
  return_after_1d numeric,
  return_after_5d numeric,
  return_after_20d numeric,
  return_after_60d numeric,
  evaluated_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists recommendation_cycles_ticker_horizon_status_idx
on recommendation_cycles (ticker, horizon, status, created_at desc);

create index if not exists recommendation_cycles_created_at_idx
on recommendation_cycles (created_at desc);
