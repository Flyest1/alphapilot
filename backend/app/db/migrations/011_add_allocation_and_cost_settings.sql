-- 011: 목표 배분/리밸런스/비용 설정 컬럼 (additive, Phase 5)
-- 기본값은 백엔드 Settings 모델 기본값과 일치한다.

alter table settings add column if not exists target_domestic_pct numeric default 40;
alter table settings add column if not exists target_global_pct numeric default 40;
alter table settings add column if not exists target_cash_pct numeric default 20;
alter table settings add column if not exists target_max_asset_pct numeric default 25;
alter table settings add column if not exists rebalance_band_pct numeric default 5;
alter table settings add column if not exists risk_per_trade_pct numeric default 1.0;
alter table settings add column if not exists fee_rate_pct numeric default 0.015;
alter table settings add column if not exists kr_tax_rate_pct numeric default 0.18;
alter table settings add column if not exists fx_spread_pct numeric default 0.5;
