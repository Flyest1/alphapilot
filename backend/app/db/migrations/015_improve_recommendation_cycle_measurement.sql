alter table recommendation_cycles
  add column if not exists barrier_hit_at timestamptz,
  add column if not exists technical_score numeric,
  add column if not exists base_confidence numeric,
  add column if not exists calibrated_confidence numeric;
