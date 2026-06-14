-- 013: in-app notifications and Telegram opt-in settings (additive, Phase 9)

create table if not exists notifications (
  id uuid primary key default gen_random_uuid(),
  event_key text not null unique,
  event_type text not null,
  title text not null,
  message text not null,
  severity text not null default 'info',
  report_id uuid references reports(id) on delete set null,
  cycle_id uuid references recommendation_cycles(id) on delete set null,
  metadata jsonb not null default '{}'::jsonb,
  is_read boolean not null default false,
  read_at timestamptz,
  telegram_status text not null default 'not_requested',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists notifications_unread_created_at_idx
on notifications (is_read, created_at desc);

alter table settings add column if not exists telegram_notify_report_completed boolean default false;
alter table settings add column if not exists telegram_notify_target_hit boolean default false;
alter table settings add column if not exists telegram_notify_stop_hit boolean default false;
alter table settings add column if not exists telegram_notify_cycle_closed boolean default false;
alter table settings add column if not exists telegram_notify_drift_warning boolean default false;
