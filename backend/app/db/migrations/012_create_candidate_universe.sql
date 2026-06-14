-- 012: DB-backed candidate universe and seed data (additive, Phase 8)

create table if not exists candidate_universe (
  id uuid primary key default gen_random_uuid(),
  report_type text not null,
  market text not null,
  ticker text not null,
  name text not null,
  currency text not null default 'KRW',
  source text not null default 'seed',
  source_rank int,
  is_active boolean not null default true,
  refreshed_at timestamptz default now(),
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (market, ticker)
);

create index if not exists candidate_universe_report_type_active_rank_idx
on candidate_universe (report_type, is_active, source_rank, ticker);

insert into candidate_universe
  (report_type, market, ticker, name, currency, source, source_rank)
values
  ('domestic', 'KR', '005930', '삼성전자', 'KRW', 'seed', 1),
  ('domestic', 'KR', '000660', 'SK하이닉스', 'KRW', 'seed', 2),
  ('domestic', 'KR', '005380', '현대차', 'KRW', 'seed', 3),
  ('domestic', 'KR', '000270', 'Kia', 'KRW', 'seed', 4),
  ('domestic', 'KR', '035420', 'NAVER', 'KRW', 'seed', 5),
  ('domestic', 'KR', '035720', 'Kakao', 'KRW', 'seed', 6),
  ('domestic', 'KR', '068270', '셀트리온', 'KRW', 'seed', 7),
  ('domestic', 'KR', '105560', 'KB금융', 'KRW', 'seed', 8),
  ('domestic', 'KR', '055550', 'Shinhan Financial', 'KRW', 'seed', 9),
  ('domestic', 'KR', '006400', 'Samsung SDI', 'KRW', 'seed', 10),
  ('domestic', 'KR', '051910', 'LG Chem', 'KRW', 'seed', 11),
  ('domestic', 'KR', '012450', 'Hanwha Aerospace', 'KRW', 'seed', 12),
  ('domestic', 'KR', '064350', 'Hyundai Rotem', 'KRW', 'seed', 13),
  ('domestic', 'KR', '034020', 'Doosan Enerbility', 'KRW', 'seed', 14),
  ('domestic', 'KR', '069500', 'KODEX 200', 'KRW', 'seed', 15),
  ('domestic', 'KR', '091160', 'KODEX 반도체', 'KRW', 'seed', 16),
  ('domestic', 'KR', '305720', 'KODEX Battery', 'KRW', 'seed', 17),
  ('domestic', 'KR', '360750', 'TIGER US S&P500', 'KRW', 'seed', 18),
  ('domestic', 'KR', '133690', 'TIGER NASDAQ100', 'KRW', 'seed', 19),
  ('global', 'US', 'NVDA', 'NVIDIA', 'USD', 'seed', 1),
  ('global', 'US', 'MSFT', 'Microsoft', 'USD', 'seed', 2),
  ('global', 'US', 'AAPL', 'Apple', 'USD', 'seed', 3),
  ('global', 'US', 'AMZN', 'Amazon', 'USD', 'seed', 4),
  ('global', 'US', 'GOOGL', 'Alphabet', 'USD', 'seed', 5),
  ('global', 'US', 'META', 'Meta Platforms', 'USD', 'seed', 6),
  ('global', 'US', 'TSLA', 'Tesla', 'USD', 'seed', 7),
  ('global', 'US', 'AVGO', 'Broadcom', 'USD', 'seed', 8),
  ('global', 'US', 'AMD', 'AMD', 'USD', 'seed', 9),
  ('global', 'US', 'NFLX', 'Netflix', 'USD', 'seed', 10),
  ('global', 'US', 'COST', 'Costco', 'USD', 'seed', 11),
  ('global', 'US', 'JPM', 'JPMorgan Chase', 'USD', 'seed', 12),
  ('global', 'US', 'LLY', 'Eli Lilly', 'USD', 'seed', 13),
  ('global', 'US', 'V', 'Visa', 'USD', 'seed', 14),
  ('global', 'US', 'BRK.B', 'Berkshire Hathaway', 'USD', 'seed', 15),
  ('global', 'ETF', 'VOO', 'Vanguard S&P 500 ETF', 'USD', 'seed', 16),
  ('global', 'ETF', 'SPY', 'SPDR S&P 500 ETF', 'USD', 'seed', 17),
  ('global', 'ETF', 'QQQ', 'Invesco QQQ Trust', 'USD', 'seed', 18),
  ('global', 'ETF', 'SMH', 'VanEck Semiconductor ETF', 'USD', 'seed', 19),
  ('global', 'ETF', 'SCHD', 'Schwab US Dividend ETF', 'USD', 'seed', 20),
  ('global', 'ETF', 'VTI', 'Vanguard Total Stock Market ETF', 'USD', 'seed', 21),
  ('global', 'ETF', 'IWM', 'iShares Russell 2000 ETF', 'USD', 'seed', 22),
  ('global', 'ETF', 'XLK', 'Technology Select Sector SPDR', 'USD', 'seed', 23),
  ('global', 'ETF', 'GLD', 'SPDR Gold Shares', 'USD', 'seed', 24),
  ('global', 'ETF', 'TLT', 'iShares 20+ Year Treasury Bond ETF', 'USD', 'seed', 25)
on conflict (market, ticker) do nothing;
