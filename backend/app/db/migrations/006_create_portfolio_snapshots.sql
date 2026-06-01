create table if not exists portfolio_snapshots (
  id uuid primary key default gen_random_uuid(),
  report_id uuid references reports(id) on delete set null,
  report_type text not null,
  snapshot_date date not null default current_date,
  total_market_value numeric not null default 0,
  total_cost numeric not null default 0,
  total_profit_loss numeric not null default 0,
  total_return_rate numeric not null default 0,
  daily_profit_loss numeric not null default 0,
  daily_return_rate numeric not null default 0,
  domestic_value numeric not null default 0,
  global_value numeric not null default 0,
  cash_value numeric not null default 0,
  usd_krw_rate numeric not null default 1400,
  asset_allocation jsonb not null default '[]'::jsonb,
  asset_returns jsonb not null default '[]'::jsonb,
  created_at timestamptz default now()
);

create index if not exists portfolio_snapshots_created_at_idx
on portfolio_snapshots (created_at desc);

create index if not exists portfolio_snapshots_report_type_created_at_idx
on portfolio_snapshots (report_type, created_at desc);
