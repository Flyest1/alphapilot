-- 008: 시장 데이터 일중 캐시 영속화 (additive)
-- 백엔드 프로세스 재시작(콜드스타트) 후에도 같은 날 조회한 시세를 재사용해
-- pykrx/yfinance 재호출 폭주를 막는다.

create table if not exists market_data_cache (
    cache_key text primary key,
    payload jsonb not null,
    created_at timestamptz not null default now()
);

comment on table market_data_cache is
    '시장 데이터 일중 캐시. cache_key는 market:ticker:lookback:stale_days:date 형식.';
