-- 019: Expand the curated US equity universe used by global advisory screens.

insert into candidate_universe
  (report_type, market, ticker, name, currency, source, source_rank)
values
  ('global', 'US', 'ORCL', 'Oracle', 'USD', 'seed', 16),
  ('global', 'US', 'CRM', 'Salesforce', 'USD', 'seed', 17),
  ('global', 'US', 'ADBE', 'Adobe', 'USD', 'seed', 18),
  ('global', 'US', 'QCOM', 'Qualcomm', 'USD', 'seed', 19),
  ('global', 'US', 'TXN', 'Texas Instruments', 'USD', 'seed', 20),
  ('global', 'US', 'UNH', 'UnitedHealth Group', 'USD', 'seed', 21),
  ('global', 'US', 'JNJ', 'Johnson & Johnson', 'USD', 'seed', 22),
  ('global', 'US', 'PFE', 'Pfizer', 'USD', 'seed', 23),
  ('global', 'US', 'XOM', 'Exxon Mobil', 'USD', 'seed', 24),
  ('global', 'US', 'CVX', 'Chevron', 'USD', 'seed', 25),
  ('global', 'US', 'WMT', 'Walmart', 'USD', 'seed', 26),
  ('global', 'US', 'HD', 'Home Depot', 'USD', 'seed', 27),
  ('global', 'US', 'NKE', 'Nike', 'USD', 'seed', 28),
  ('global', 'US', 'DIS', 'Walt Disney', 'USD', 'seed', 29),
  ('global', 'US', 'PYPL', 'PayPal', 'USD', 'seed', 30)
on conflict (market, ticker) do update
set report_type = excluded.report_type,
    name = excluded.name,
    currency = excluded.currency,
    source_rank = excluded.source_rank,
    is_active = true,
    updated_at = now();
