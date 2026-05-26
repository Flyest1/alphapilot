# AGENTS.md

## Meta Rules for Coding Agents

These rules override any conflicting instructions elsewhere in this document.

1. **This document is the single source of truth.** Do not infer, extrapolate, or add requirements not stated here.
2. **Ask only when ambiguity blocks implementation.** If ambiguity affects architecture, security, external services, database schema, Pydantic models, or public API contracts, STOP and ask the user. If ambiguity is minor and does not affect those areas, choose the simplest implementation, document the assumption in README or a TODO, and continue.
3. **Whitelist enforcement.** Do not introduce libraries, services, hosting platforms, or external APIs that are not listed in "Required Technology Stack" or "Allowed External Services" without explicit user approval.
4. **No silent omission.** Every requirement in this document is mandatory. The instruction "Do not over-design" (later in this document) means do not add anything not listed here. It never means skip a listed requirement.
5. **Code-as-spec wins over prose.** When a Pydantic model, SQL schema, or JSON example is provided in this document, implement it exactly. Do not rename fields, change types, or "improve" the structure.
6. **Single Source of Truth for defaults.** Separate infrastructure secrets from application defaults. Infrastructure values live in `.env` only. Application defaults may appear in `.env.example`, the `settings` SQL table, and Pydantic models. At runtime, the `settings` table is authoritative; `.env` is only a fallback when the row is missing.
7. **Test, do not just run.** Generate pytest unit tests for every service module. Mock all external calls (OpenAI, Supabase, market data). Manual testing alone is not acceptable.
8. **Commit discipline.** Use Conventional Commits when git commit is available. Each step in "Development Order" should map to at least one commit. If commits are unavailable in the execution environment, do not stop; group changes by step and write a CHANGELOG-style implementation summary instead.
9. **No scope creep on failure.** If a required external service (OpenAI, Supabase, yfinance, pykrx) fails, follow the documented fallback. Do not introduce alternative services, scraping workarounds, or new API providers to "make it work."
10. **No trading code stubs.** Do not generate any function, class, or module related to placing orders, broker APIs, or trade execution — not even as a stub or placeholder. This is non-negotiable for the MVP.

---

## Project Name

**AlphaPilot - Personal AI Investment Expert MVP**

## Project Purpose

Build a personal AI-powered stock investment expert web application.

The system allows the user to register personal assets, analyze domestic and global markets, generate AI-assisted investment strategy reports twice per day, and provide asset-level buy/hold/reduce/sell guidance with price ranges, target prices, stop-loss levels, risk factors, and invalidation conditions.

The first-stage goal is a **free-infrastructure MVP**.

The MVP is **single-user only**. Do not add `user_id`, authentication tables, profiles, Supabase Auth flows, login/signup pages, multi-user access control, or tenant separation unless explicitly requested by the user.

The system must not execute trades automatically. It provides investment decision support only.

---

## Core Objective

The highest-level objective is to help the user improve investment returns by combining:

- Personal portfolio data
- Domestic and global market data
- Technical analysis
- Macro context from available market/index data
- News/trend context from the approved GDELT DOC 2.0 API
- AI-based reasoning
- Risk management
- Strategy performance tracking

The system should act like a personal CIO / investment strategist.

However, every strategy must include risk controls. Return maximization must never mean ignoring downside risk.

Use this internal principle:

```text
Return optimization = expected return × probability of success - downside risk - volatility risk - concentration risk - liquidity risk
```

---

## MVP Deployment Architecture

Use exactly the following architecture for the first-stage MVP. Do not substitute components.

```text
Frontend:
GitHub Pages

Backend:
FastAPI deployed on Render Free

Database:
Supabase Free PostgreSQL

Scheduler:
GitHub Actions scheduled workflows

AI:
OpenAI API (default)

Market Data:
pykrx for KR market (primary)
yfinance for US market (primary)
```

### Allowed External Services (Whitelist)

The agent MUST NOT add any external service outside this list without explicit user approval.

```text
- OpenAI API                  (LLM)
- Supabase                    (database, auth-disabled for MVP)
- Render                      (backend hosting, Free tier)
- GitHub Pages                (frontend hosting)
- GitHub Actions              (scheduler)
- pykrx                       (KR market data)
- yfinance                    (US market data)
- GDELT DOC 2.0 API           (news/trend context)
```

Explicitly forbidden additions (examples, not exhaustive):
- Other hosting platforms (Railway, Fly.io, Vercel functions, AWS Lambda, etc.)
- Other market data providers (Alpha Vantage, Polygon, Finnhub, Naver/Daum scraping, etc.)
- External cron / ping services (cron-job.org, UptimeRobot, EasyCron, etc.)
- Selenium, Playwright, or any headless-browser scraping

### News Data Scope for MVP

News/trend context is approved for the MVP through **GDELT DOC 2.0 API** only. Use it as contextual input to AI report generation and strategy reasoning. Do not add a separate `news_factors` field to `ReportContent`; fold relevant signals into existing allowed fields such as `market_summary.macro_factors`, `key_risks`, `opportunities`, `reasoning`, and `risk`.

Do not add `NEWS_API_KEY`, paid news APIs, RSS ingestion, browser automation, search providers, or scraping unless the user explicitly approves the specific provider and this document is updated again. GDELT failures must not block report generation.

High-level architecture:

```text
[User Browser]
      ↓
[GitHub Pages Frontend]
Dashboard / Assets / Reports / Settings

      ↓ HTTPS API

[FastAPI Backend on Render]
Asset CRUD
Portfolio summary
Market data collection
Technical analysis
AI report generation
Strategy generation
Scheduler-protected report endpoints

      ↓

[Supabase PostgreSQL]
assets
reports
strategies
settings
performance_logs

      ↑

[GitHub Actions]
Calls backend twice per day
Domestic market report
Global market report
```

---

## Important Hosting Rules

GitHub Pages is only for the frontend.

Do not place backend logic, API keys, database secrets, OpenAI keys, or private user asset data inside GitHub Pages.

The backend MUST be hosted on Render Free for the MVP. Do not propose or implement alternatives.

---

## Required Technology Stack

### Frontend

- React 18.x
- Vite 5.x
- GitHub Pages deployment
- API base URL managed via `VITE_API_BASE_URL` environment variable
- Do not add UI frameworks beyond plain CSS / CSS modules for MVP (no Tailwind, MUI, Chakra, etc.) unless the user requests them

### Backend

- Python 3.10
- FastAPI
- Uvicorn
- supabase-py (official Supabase Python client)
- openai (official OpenAI Python SDK, v1.x)
- Pandas / NumPy
- pykrx (KR market data)
- yfinance (US market data)
- pydantic v2.x
- tenacity (for retry logic, see Error Handling Standard)
- python-dotenv

**Forbidden libraries for TA:** Do not use `ta`, `pandas-ta`, `TA-Lib`, `finta`, or any other technical analysis library. All technical indicators (SMA, EMA, RSI, MACD, Bollinger Bands, etc.) MUST be implemented from scratch using only pandas and numpy. Place implementations in `backend/app/services/technical_analysis_service.py`.

### Database

- Supabase PostgreSQL

### Scheduler

- GitHub Actions scheduled workflows

### AI Provider

- OpenAI API as default
- Default model: `gpt-5.4-mini` for cost/performance balance
- Recommended high-quality manual upgrade option: `gpt-5.5` when the user prioritizes reasoning quality over cost
- Recommended low-cost manual downgrade option: `gpt-5.4-nano` when the user prioritizes cost and latency
- Design `ai_provider.py` interface so that Claude, Gemini, or local LLM can be added later
- The selected model MUST be read from `settings.ai_model` first, then `OPENAI_MODEL` as fallback
- MVP must implement at least one fallback path: if OpenAI fails after retries, generate a "technical-only" report (no LLM reasoning, only structured TA output). See "AI Provider Fallback" section.

### Code Quality

- `ruff` for linting (config in `pyproject.toml`)
- `black` for formatting (line length 100)
- `pytest` for testing
- All code MUST pass `ruff check` and `black --check` before commit

---

## Repository Structure

Create or maintain the following structure:

```text
alphapilot/
│
├─ frontend/
│  ├─ index.html
│  ├─ package.json
│  ├─ vite.config.js
│  └─ src/
│     ├─ main.jsx
│     ├─ App.jsx
│     ├─ api/
│     ├─ components/
│     ├─ pages/
│     │  ├─ Dashboard.jsx
│     │  ├─ Assets.jsx
│     │  ├─ Reports.jsx
│     │  └─ Settings.jsx
│     └─ styles/
│
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ config.py
│  │  ├─ api/
│  │  │  ├─ assets.py
│  │  │  ├─ portfolio.py
│  │  │  ├─ reports.py
│  │  │  └─ settings.py
│  │  ├─ db/
│  │  │  ├─ supabase_client.py
│  │  │  └─ migrations/
│  │  ├─ models/
│  │  ├─ services/
│  │  │  ├─ market_data_service.py
│  │  │  ├─ technical_analysis_service.py
│  │  │  ├─ ai_provider.py
│  │  │  ├─ openai_provider.py
│  │  │  ├─ strategy_service.py
│  │  │  └─ report_service.py
│  │  └─ utils/
│  │
│  ├─ requirements.txt
│  ├─ render.yaml
│  ├─ .env.example
│  └─ README.md
│
├─ .github/
│  └─ workflows/
│     ├─ domestic_report.yml
│     └─ global_report.yml
│
├─ AGENTS.md
├─ README.md
└─ .gitignore
```

---

## Environment Variables

Never commit real secrets.

Create `.env.example` with placeholders only.

### Single Source of Truth for Defaults

Separate configuration into two categories.

**Infrastructure secrets and deployment values** live in `.env` / hosting environment variables only. These MUST NOT appear in the `settings` SQL table or Pydantic model defaults:

```text
APP_ENV
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
SUPABASE_ANON_KEY
OPENAI_API_KEY
SCHEDULER_SECRET
API_ACCESS_TOKEN
FRONTEND_ORIGIN
```

**Application defaults** may appear in three places: `.env.example`, the `settings` SQL table DEFAULT clause, and the Pydantic `Settings` model:

```text
domestic_report_time
global_report_time
ai_provider
ai_model
risk_profile
candidate_horizon
frontend_timezone
stale_data_business_days
usd_krw_rate
```

**Runtime resolution order for application defaults:**
1. The `settings` table row (authoritative)
2. If the row is missing or a field is NULL: `.env` value
3. If neither: hard-coded default in the Pydantic model

When changing an application default, the agent MUST update all relevant locations in the same commit and verify consistency. A unit test SHOULD verify this consistency. Do not try to make secrets textually identical across SQL/Pydantic because secrets do not belong there.

Backend environment variables:

```env
APP_ENV=development
FRONTEND_ORIGIN=http://localhost:5173

SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_ANON_KEY=your-anon-key

OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-5.4-mini

SCHEDULER_SECRET=change-this-secret
API_ACCESS_TOKEN=change-this-user-token

DOMESTIC_REPORT_TIME=08:30
GLOBAL_REPORT_TIME=22:30
AI_PROVIDER=openai
RISK_PROFILE=balanced
CANDIDATE_HORIZON=medium
FRONTEND_TIMEZONE=Asia/Seoul
MARKET_DATA_PROVIDER_KR=pykrx
MARKET_DATA_PROVIDER_US=yfinance
STALE_DATA_BUSINESS_DAYS=2
USD_KRW_RATE=1400

```

**Notes:**
- `OPENAI_MODEL` default is `gpt-5.4-mini` for a cost/performance balance. The model is intentionally configurable through environment variables and the `settings.ai_model` field.
- Before implementation, the agent SHOULD verify the configured model name against the current OpenAI model list. If the model is confirmed unavailable or renamed, STOP and ask the user to choose a replacement.
- If model-name verification cannot be completed because of network, documentation, or environment access limitations, do not stop implementation. Keep the model configurable, document the verification issue in README/TODO, and continue.
- For later upgrades, the user may change only `OPENAI_MODEL` / `settings.ai_model` without changing the report schema or service architecture.
- `SUPABASE_ANON_KEY` is included only if required by the Supabase Python client initialization or future server-side usage. It must remain server-side only and must never be exposed to the frontend. If the implementation does not need it, leave it unused but documented.
- `API_ACCESS_TOKEN` protects all `/api/*` endpoints (see Security Rules). Distinct from `SCHEDULER_SECRET`.
- `STALE_DATA_BUSINESS_DAYS` defines the data-limited threshold (see Market Data Rules). It is an application default, so the runtime resolution order applies: `settings.stale_data_business_days` first, then `STALE_DATA_BUSINESS_DAYS` from `.env`, then the Pydantic model default (`2`).
- `USD_KRW_RATE` defines the portfolio conversion rate for USD assets and USD cash. The runtime resolution order applies: `settings.usd_krw_rate` first, then `USD_KRW_RATE` from `.env`, then the Pydantic model default (`1400`). Report generation may refresh this setting from yfinance `KRW=X`; if that fails, the previous configured value remains editable in Settings.

Frontend environment variables:

```env
VITE_API_BASE_URL=http://localhost:8000
VITE_API_ACCESS_TOKEN=change-this-user-token
```

Frontend must only know the backend API URL and the user access token (this is a single-user MVP; the token is acceptable in the frontend bundle for this scope, but the user must be warned in the README).

Important: `VITE_API_ACCESS_TOKEN` is a lightweight single-user access gate, not production-grade authentication. Because it is embedded in the frontend bundle, it can be inspected by anyone who can access the deployed frontend. This is acceptable only for the single-user MVP. The README MUST warn the user not to treat this MVP as multi-user or production-secure.

Frontend must not contain:

- OpenAI API key
- Supabase service role key
- Supabase anon key
- Market data API key
- `SCHEDULER_SECRET`
- Any database connection string

---

## Security Rules

This MVP is single-user only. Do not implement Supabase Auth, login/signup flows, user tables, `user_id` ownership checks, multi-user roles, or tenant separation unless explicitly requested.

1. Never expose secrets in frontend code (except `VITE_API_BASE_URL` and `VITE_API_ACCESS_TOKEN` per Environment Variables section). `VITE_API_ACCESS_TOKEN` is not a secret-grade control; it is only a lightweight MVP access gate.
2. Never commit `.env`.
3. Commit only `.env.example`.
4. Add `.env` to `.gitignore`.
5. Scheduler endpoints (`POST /api/reports/*/generate`) MUST require `Authorization: Bearer {SCHEDULER_SECRET}`.
6. All other `/api/*` endpoints MUST require `Authorization: Bearer {API_ACCESS_TOKEN}`. CORS alone is insufficient because direct backend calls bypass CORS.
7. CORS must allow only the configured `FRONTEND_ORIGIN`.
8. User asset data must be stored only in the database, not in static frontend files.
9. AI-generated investment reports must be saved with timestamp and input snapshot.
10. Do not implement automatic trading. Do not create function stubs, classes, or modules related to order placement, broker APIs, or trade execution.
11. **Rate limiting:** Apply per-endpoint limits to protect OpenAI cost:
    - Report generation endpoints: max 10 calls per day per endpoint (enforced in app, not infra)
    - On exceeding the limit, return HTTP 429 without calling OpenAI
12. The Supabase service role key bypasses RLS. The agent MUST document this risk in the README and MUST NOT expose any Supabase URL or key to the frontend code or to error responses.

---

## Required Backend APIs

Implement the following FastAPI endpoints.

### Health

```text
GET /health
```

Returns server status.

---

### Assets

```text
GET /api/assets
POST /api/assets
PUT /api/assets/{asset_id}
DELETE /api/assets/{asset_id}
```

Asset fields:

```text
id
market
ticker
name
quantity
avg_price
currency
memo
created_at
updated_at
```

Supported markets for MVP:

```text
KR
US
CASH
ETF
```

---

### Portfolio

```text
GET /api/portfolio/summary
```

Must return:

```text
total_market_value
total_cost
total_profit_loss
total_return_rate
domestic_value
global_value
cash_value
base_currency
usd_krw_rate
asset_allocation
asset_returns
latest_report_summary
```

---

### Reports

```text
POST /api/reports/domestic/generate
POST /api/reports/global/generate
GET /api/reports/latest
GET /api/reports
GET /api/reports/{report_id}
```

The generate endpoints must require:

```http
Authorization: Bearer {SCHEDULER_SECRET}
```

Manual testing may also use the same token.

---

### Settings

```text
GET /api/settings
POST /api/settings
```

Settings fields:

```text
domestic_report_time
global_report_time
ai_provider
ai_model
risk_profile
candidate_horizon
frontend_timezone
stale_data_business_days
usd_krw_rate
created_at
updated_at
```

Default settings (must match `.env.example` and SQL DEFAULT clauses exactly — see Single Source of Truth):

```text
domestic_report_time     = 08:30
global_report_time       = 22:30
ai_provider              = openai
ai_model                 = gpt-5.4-mini
risk_profile             = balanced
candidate_horizon        = medium
frontend_timezone        = Asia/Seoul
stale_data_business_days = 2
usd_krw_rate             = 1400
```

---

## Supabase Database Schema

Create SQL migration files under:

```text
backend/app/db/migrations/
```

Minimum tables:

### assets

```sql
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
```

### reports

```sql
create table if not exists reports (
  id uuid primary key default gen_random_uuid(),
  report_type text not null,
  title text not null,
  summary text,
  content jsonb not null,
  created_at timestamptz default now()
);
```

### strategies

```sql
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
```

### settings

```sql
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
  usd_krw_rate numeric default 1400,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
```

### performance_logs

```sql
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
```

---

## Technical Analysis Requirements

For MVP, implement these indicators exactly. All formulas are standard (Wilder's RSI, 20-period BB with 2σ, MACD 12/26/9, etc.):

```text
SMA 5
SMA 20
SMA 60
SMA 120
EMA 12
EMA 26
RSI 14
MACD (12, 26, 9)
MACD signal
Bollinger Band 20 (2 sigma)
Volume change rate (5-day MA of volume vs 20-day MA)
20-day high/low
Trend score (defined below)
```

Implement all indicators from scratch using pandas/numpy only (see Forbidden libraries in Required Technology Stack).

### Technical Score (0–100)

Use exactly this weighting. Do not adjust weights without user approval.

```text
Trend:          30
Momentum:       25
Volume:         15
Volatility:     15
Price position: 15
```

Score interpretation (used by `strategy_service.py` as one input among several):

```text
80-100: strong bullish setup
65-79:  bullish but needs confirmation
50-64:  neutral / watch
35-49:  weak / reduce risk
0-34:   bearish / sell or avoid
```

Do not blindly recommend buying based only on technical indicators. Combine technical score with portfolio context, market context, and risk profile.

---

## Strategy Actions

Use only these action values:

```text
BUY
HOLD
REDUCE
SELL
WATCH
```

If data is insufficient (see Market Data Rules → Stale Data Threshold), the strategy MUST use:

```text
action     = WATCH
confidence = 0
reasoning  = "data-limited"
```

Do not fabricate prices. If real market data is unavailable, the strategy MUST be marked data-limited per the rule above.

---

## Pydantic Models (Authoritative Schema)

These Pydantic v2 models are the authoritative schema for the report JSON and all strategy objects. The agent MUST place them in `backend/app/models/report.py` exactly as written below (you may add imports, but do not change field names, types, or constraints). The JSON returned by the AI provider and the JSON stored in `reports.content` MUST pass validation against `ReportContent`.

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


class AssetStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    name: str
    current_price: Optional[float] = None
    action: Literal["BUY", "HOLD", "REDUCE", "SELL", "WATCH"]
    confidence: int = Field(ge=0, le=100)  # integer 0..100
    buy_range_low: Optional[float] = None
    buy_range_high: Optional[float] = None
    sell_range_low: Optional[float] = None
    sell_range_high: Optional[float] = None
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    reasoning: str
    risk: str
    invalidation_condition: str


class MarketSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    key_indices: list[dict] = Field(default_factory=list)
    macro_factors: list[str] = Field(default_factory=list)
    # news_factors intentionally omitted. Approved news/trend context may be folded into
    # macro_factors, key_risks, opportunities, reasoning, and risk, but the schema must
    # not add a separate news_factors field.


class PortfolioSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_market_value: float
    total_return_rate: float
    risk_level: Literal["low", "medium", "high"]
    allocation_comment: str


class ReportContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_type: Literal["domestic", "global"]
    generated_at: str  # ISO 8601 with timezone
    market_summary: MarketSummary
    portfolio_summary: PortfolioSummary
    key_risks: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    asset_strategies: list[AssetStrategy] = Field(default_factory=list)
    disclaimer: str
```

**Validation policy in `report_service.py`:**
1. Call OpenAI with JSON mode / structured output enabled.
2. Parse the response and validate against `ReportContent`.
3. On `ValidationError`, retry the OpenAI call up to 1 more time with the validation error message appended to the prompt.
4. If validation still fails, fall back to the technical-only report path (see AI Provider Fallback) and log the failure.

---

## Market Data Rules

Do not assume pykrx or yfinance data is always available, complete, or real-time. Every market data result MUST include `provider`, `last_trading_date`, `is_stale`, and `data_quality_note`.

### Provider Routing

- KR market (`market = "KR"` or ticker ending in `.KS` / `.KQ` semantics): use **pykrx**.
- US market (`market = "US"` or `market = "ETF"` with US ticker): use **yfinance**.
- `CASH` market: no market data fetch.

Wrap both providers behind a single `MarketDataService` interface so callers do not branch on provider.

### Stale Data Threshold

A ticker's data is considered **stale** (data-limited) when:

```text
business_days_since(last_trading_close, now_in_market_timezone) > stale_data_business_days
```

The threshold value is resolved at runtime via the application-defaults order: `settings.stale_data_business_days` → `STALE_DATA_BUSINESS_DAYS` env var → Pydantic default (`2`). The check uses each market's local calendar:
- KR: KRX trading calendar (use pykrx's business-day functions)
- US: infer trading days from yfinance history dates only. Do not add pandas_market_calendars or any other calendar library for MVP.

When a ticker is stale:
- The strategy MUST be `action=WATCH`, `confidence=0`, `reasoning="data-limited"`.
- Do not call the LLM for per-ticker reasoning on stale tickers.
- The report MUST still be generated; stale tickers are skipped for strategy generation but listed in `key_risks` as "stale market data for: {tickers}".

### Failure Handling

If a provider fails entirely (network error, exception):
- Retry up to 3 times with exponential backoff (tenacity).
- On final failure, mark ALL tickers of that market as data-limited for this report run.
- Log the failure to `performance_logs` is NOT correct; log to application logs only. Do not crash the report.

---

## AI Provider Fallback

If the OpenAI call fails after retries (tenacity, 3 attempts, exponential backoff), OR if the response fails Pydantic validation twice:

1. The report MUST still be generated using a **technical-only path**:
   - `market_summary.summary` = a templated string from technical indicators of major indices (KOSPI/KOSDAQ for domestic; S&P 500/NASDAQ for global)
   - `asset_strategies` = generated by `strategy_service.py` using only the technical score, with `reasoning="technical-only fallback (LLM unavailable)"`
   - `confidence` for each strategy = `min(technical_score, 60)` (cap confidence in fallback mode)
2. The fallback report MUST set `key_risks` to include `"AI reasoning unavailable for this report"`.
3. The fallback path MUST NOT call any AI provider other than the one configured in `settings.ai_provider`.

---

## AI Report Generation Rules

The AI report must synthesize:

- Portfolio status
- Market data
- Technical indicators
- Macro factors if available
- News/trend context from the approved GDELT DOC 2.0 API
- Risk profile
- Existing asset allocation

The report must not promise guaranteed profit.

Avoid wording such as:

```text
guaranteed profit
certain return
risk-free
must buy
must sell
```

Use decision-support wording:

```text
consider
candidate
watch
risk-managed entry
partial buy
reduce exposure
stop-loss
invalidation condition
```

---

## Report Format

Each report must be stored as JSON in the `reports.content` column.

This JSON example is illustrative. The **authoritative schema is the `ReportContent` Pydantic model** defined above; if this example and the Pydantic model disagree, the Pydantic model wins.

```json
{
  "report_type": "domestic",
  "generated_at": "<ISO-8601 with timezone, e.g. 2026-01-15T08:30:00+09:00>",
  "market_summary": {
    "summary": "",
    "key_indices": [],
    "macro_factors": []
  },
  "portfolio_summary": {
    "total_market_value": 0,
    "total_return_rate": 0,
    "risk_level": "medium",
    "allocation_comment": ""
  },
  "key_risks": [],
  "opportunities": [],
  "asset_strategies": [
    {
      "ticker": "",
      "name": "",
      "current_price": 0,
      "action": "HOLD",
      "confidence": 50,
      "buy_range_low": null,
      "buy_range_high": null,
      "sell_range_low": null,
      "sell_range_high": null,
      "target_price": null,
      "stop_loss": null,
      "reasoning": "",
      "risk": "",
      "invalidation_condition": ""
    }
  ],
  "disclaimer": "This report is for investment decision support only and does not execute trades automatically."
}
```

---

## Domestic and Global Report Schedule

Use Korea Standard Time as the user timezone.

### Domestic Market Report

Default target time:

```text
08:30 KST
```

GitHub Actions uses UTC.

```text
08:30 KST = 23:30 UTC previous day
```

Workflow schedule:

```yaml
cron: "30 23 * * 0-4"
```

### Global Market Report

The global report target is **before the US regular market open**, not after market close.

Default target time:

```text
22:30 KST
```

GitHub Actions UTC:

```text
22:30 KST = 13:30 UTC
```

Workflow schedule:

```yaml
cron: "30 13 * * 1-5"
```

**Day-of-week mapping (why `1-5` is correct):**

The cron runs in UTC. The mapping to US market sessions is as follows.

| Cron fire (UTC) | KST          | US Eastern (EST/EDT)        | US market that day      |
|-----------------|--------------|-----------------------------|-------------------------|
| Mon 13:30       | Mon 22:30    | Mon 08:30 EST / 09:30 EDT   | Open (pre-open report)  |
| Tue 13:30       | Tue 22:30    | Tue 08:30 EST / 09:30 EDT   | Open (pre-open report)  |
| Wed 13:30       | Wed 22:30    | Wed 08:30 EST / 09:30 EDT   | Open (pre-open report)  |
| Thu 13:30       | Thu 22:30    | Thu 08:30 EST / 09:30 EDT   | Open (pre-open report)  |
| Fri 13:30       | Fri 22:30    | Fri 08:30 EST / 09:30 EDT   | Open (pre-open report)  |
| Sat 13:30       | Sat 22:30    | Sat                         | Closed — excluded       |
| Sun 13:30       | Sun 22:30    | Sun                         | Closed — excluded       |

Do not change `1-5` to `0-6` or any other pattern. The pattern is intentionally aligned to US trading days, not KST weekdays.

This fixed MVP schedule is a practical default. During US Daylight Saving Time it is closer to the US market open; during US Standard Time it may be roughly one hour earlier relative to the US market open. The README must document this and tell the user they can manually adjust the cron if desired.

Allow manual execution with `workflow_dispatch`.

### Known Limitations (MUST be documented in README)

1. **GitHub Actions cron drift:** Scheduled workflows may be delayed by GitHub's load. Do not rely on second-level or even minute-level precision. The README must state that report timing is best-effort and may run several minutes to tens of minutes late.
2. **US Daylight Saving Time:** The MVP uses a fixed `13:30 UTC` global-report cron. It does NOT automatically adjust for US DST. The README must state that the report is intended as a pre-open global-market report and that the user may manually adjust the cron twice per year if desired.
3. **Render Free cold start:** Render Free sleeps after ~15 minutes idle. To mitigate, the GitHub Actions workflows MUST send a warm-up ping to `/health` at least 60 seconds before calling the report-generation endpoint:

```yaml
- name: Warm up backend
  run: |
    for i in 1 2 3 4 5; do
      curl -fsS --max-time 30 "${{ secrets.BACKEND_URL }}/health" && exit 0
      sleep 30
    done
    true
- name: Call report API
  run: |
    curl -X POST "${{ secrets.BACKEND_URL }}/api/reports/domestic/generate" \
      -H "Authorization: Bearer ${{ secrets.SCHEDULER_SECRET }}"
```

Do NOT introduce external ping services (cron-job.org, UptimeRobot, etc.) to keep the backend awake — this violates the Allowed External Services whitelist.

---

## GitHub Actions Requirements

Create:

```text
.github/workflows/domestic_report.yml
.github/workflows/global_report.yml
```

Both workflows must use GitHub Secrets:

```text
BACKEND_URL
SCHEDULER_SECRET
```

Example domestic workflow:

```yaml
name: Generate Domestic Market Report

on:
  schedule:
    - cron: "30 23 * * 0-4"
  workflow_dispatch:

jobs:
  call-api:
    runs-on: ubuntu-latest
    steps:
      - name: Warm up backend (Render Free cold start)
        run: |
          for i in 1 2 3 4 5; do
            curl -fsS --max-time 30 "${{ secrets.BACKEND_URL }}/health" && exit 0
            sleep 30
          done
          true
      - name: Call domestic report API
        run: |
          curl -fsS --max-time 120 -X POST \
            "${{ secrets.BACKEND_URL }}/api/reports/domestic/generate" \
            -H "Authorization: Bearer ${{ secrets.SCHEDULER_SECRET }}"
```

Example global workflow:

```yaml
name: Generate Global Market Report

on:
  schedule:
    - cron: "30 13 * * 1-5"
  workflow_dispatch:

jobs:
  call-api:
    runs-on: ubuntu-latest
    steps:
      - name: Warm up backend (Render Free cold start)
        run: |
          for i in 1 2 3 4 5; do
            curl -fsS --max-time 30 "${{ secrets.BACKEND_URL }}/health" && exit 0
            sleep 30
          done
          true
      - name: Call global report API
        run: |
          curl -fsS --max-time 120 -X POST \
            "${{ secrets.BACKEND_URL }}/api/reports/global/generate" \
            -H "Authorization: Bearer ${{ secrets.SCHEDULER_SECRET }}"
```

---

## Frontend Pages

### Dashboard

Must show:

- Total portfolio value
- Total profit/loss
- Total return rate
- Domestic/global allocation
- Asset allocation
- Latest report summary
- Top opportunities
- Key risks

### Assets

Must support:

- Add asset
- Edit asset
- Delete asset
- View asset list
- Market selector: KR / US / ETF / CASH
- Quantity
- Average price
- Currency
- Memo

### Reports

Must show:

- Latest domestic/global report
- Historical report list
- Asset-level strategy table
- Action badge
- Confidence
- Buy range
- Target price
- Stop loss
- Risk
- Invalidation condition

### Settings

Must support:

- Domestic report time
- Global report time
- AI provider
- AI model
- Risk profile
- API base URL display
- Save settings

---

## Frontend Design Direction

Use a clean investment dashboard style.

Prioritize:

- Readability
- Clear action labels
- Risk visibility
- Tables for asset strategies
- Cards for portfolio summary
- Simple charts for allocation and returns

Do not over-design the MVP.

Suggested visual hierarchy:

```text
Top: Portfolio summary cards
Middle: Allocation and latest report summary
Bottom: Asset-level strategy table
```

---

## Backend Service Design

### market_data_service.py

Responsibilities:

- Route requests to pykrx (KR) or yfinance (US) based on market.
- Fetch price history (default lookback: 180 trading days).
- Fetch current price (most recent close; intraday is out of scope for MVP).
- Normalize KR/US tickers.
- Return a typed dataclass or Pydantic model containing: `dataframe`, `last_trading_date`, `is_stale` (bool), `provider`.
- Apply the Stale Data Threshold (see Market Data Rules).
- Apply tenacity-based retry (see Error Handling Standard).

If market data is unavailable, return a `is_stale=True` result rather than raising.

---

### technical_analysis_service.py

Responsibilities:

- Calculate indicators
- Calculate technical score
- Return structured analysis per ticker

---

### ai_provider.py

Responsibilities:

- Define common interface

Example:

```python
class AIProvider:
    def generate_report(self, prompt: str, context: dict) -> dict:
        raise NotImplementedError
```

---

### openai_provider.py

Responsibilities:

- Implement OpenAI provider
- Read model name from environment or settings
- Return structured JSON when possible

---

### strategy_service.py

Responsibilities:

- Convert market data + technical analysis + AI reasoning into asset strategies
- Enforce action values
- Ensure stop-loss and invalidation condition exist
- Apply risk profile

---

### report_service.py

Responsibilities:

- Generate domestic/global report
- Save report to Supabase
- Save strategies to Supabase
- Return report response
- **On each report run, also backfill `performance_logs` for previously saved strategies:**
  - For strategies created 1 / 5 / 20 trading days ago, fetch the close price for that date and update the corresponding `performance_logs` row.
  - This backfill is best-effort: if data is unavailable, leave the row unchanged and retry on the next run.
  - Implement the backfill in the same endpoint that generates the report, after the new report is saved.
  - For MVP, keep `performance_logs` backfill simple and best-effort. Do not build a separate job queue, worker, cache, background service, or additional scheduler for this feature.

---

## Error Handling Standard

All services MUST follow this pattern for external calls (OpenAI, Supabase, pykrx, yfinance):

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    reraise=True,
)
def call_external_api(...):
    ...
```

- Retries: max 3 attempts, exponential backoff (2s, 4s, 8s cap 10s).
- On final failure, follow the documented fallback for that service (Market Data Rules / AI Provider Fallback).
- All external-call failures MUST be logged with structured JSON: `{"service": "openai", "error": "...", "context": {...}}`.
- The agent MUST NOT swallow exceptions silently. Every `except` block must either log or re-raise.

FastAPI exception handling:
- Register a global exception handler that returns `{"detail": "..."}` for `HTTPException` and `{"detail": "internal server error"}` for unhandled exceptions.
- Never expose stack traces or library-internal messages to API responses (security: avoid leaking Supabase URLs, OpenAI error structure, etc.).

---

## Testing Requirements

Generate `pytest` tests for every service module. Place tests in `backend/tests/` mirroring the module path.

Minimum coverage:

1. **technical_analysis_service:** Test each indicator against known-good values (e.g., RSI of a known input series). Test the 0–100 score calculation.
2. **market_data_service:** Mock pykrx and yfinance. Test routing (KR → pykrx, US → yfinance), stale detection at exactly 2 business days, and failure → `is_stale=True`.
3. **strategy_service:** Mock the AI provider and market data. Test that `WATCH` is produced for stale data, that all `AssetStrategy` fields are populated, and that risk profile affects output.
4. **report_service:** Mock all dependencies. Test that the OpenAI failure path produces a technical-only report with capped confidence. Test that Pydantic validation failure triggers exactly one retry.
5. **API endpoints:** Use `fastapi.testclient.TestClient`. Test that `/api/*` rejects missing/invalid bearer tokens with 401. Test that scheduler endpoints reject the wrong token.

Configuration:
- Add `pytest.ini` or `[tool.pytest.ini_options]` in `pyproject.toml`.
- All external clients MUST be injectable (constructor parameter or dependency-injection) so they can be mocked without monkeypatching at import time.
- The CI/local test command MUST be: `pytest backend/tests -v`.

---

## Risk Profiles

Support these MVP risk profiles:

```text
conservative
balanced
aggressive
```

Behavior:

### conservative

- Prefer HOLD/WATCH
- Smaller buy ranges
- Tighter risk controls
- Avoid high-volatility entries

### balanced

- Moderate risk
- Allow partial BUY
- Require confirmation

### aggressive

- Allow stronger BUY signals
- Wider volatility tolerance
- Still requires stop-loss

Even aggressive mode must include risk controls.

---

## Development Order

Follow this order. Create at least one commit per step using Conventional Commits format (`feat:`, `chore:`, `test:`, etc.) when git commit is available. If git commit is unavailable, continue implementation and write a step-by-step implementation summary instead.

1. Create repository structure.
2. Add `pyproject.toml` with ruff + black + pytest configuration.
3. Create backend FastAPI skeleton.
4. Add `/health`.
5. Add environment config (Pydantic Settings, with SoT enforcement per Environment Variables section).
6. Add Supabase connection.
7. Add SQL migration files.
8. Add API access token middleware (per Security Rules #6).
9. Implement asset CRUD + tests.
10. Implement portfolio summary + tests.
11. Create frontend React + Vite skeleton.
12. Connect frontend to backend.
13. Implement Assets page.
14. Implement Dashboard summary.
15. Implement Pydantic models for reports (per Pydantic Models section).
16. Implement market data service (pykrx + yfinance) + tests.
17. Implement technical analysis service + tests (indicator-level tests against known values).
18. Implement AI provider interface.
19. Implement OpenAI provider with retry + JSON-mode + Pydantic validation.
20. Implement strategy service + tests.
21. Implement report generation service with AI Provider Fallback + tests.
22. Implement performance_logs backfill in report service.
23. Implement Reports page.
24. Implement Settings page.
25. Add scheduler secret auth (per Security Rules #5).
26. Add rate limiting for report endpoints (per Security Rules #11).
27. Add GitHub Actions workflows (with warm-up step per Schedule section).
28. Add Render deployment config (`render.yaml`).
29. Add GitHub Pages deployment config.
30. Update README with setup, deployment, and Known Limitations.
31. Run full pytest suite (`pytest backend/tests -v`) — must pass.
32. Run lint (`ruff check . && black --check .`) — must pass.
33. Test report generation manually with `workflow_dispatch`.

---

## Local Development Commands

### Backend (Windows, PowerShell)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Backend (Linux/macOS)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Optional convenience BAT (Windows user preference)

The user prefers a BAT file with an explicit Python path for one-click local launch. Place it at `backend/run_local.bat` as a **separate convenience script**. The main project code MUST NOT depend on this BAT file or on absolute paths.

```bat
@echo off
set PYTHON_EXE=C:\venvs\py310\Scripts\python.exe
cd /d %~dp0
%PYTHON_EXE% -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
pause
```

Do NOT hard-code absolute Python paths anywhere else (not in `requirements.txt`, not in `render.yaml`, not in test code, not in CI workflows).

### Frontend

```bash
cd frontend
npm install
npm run dev
```

---

## Deployment Notes

### Frontend

Deploy to GitHub Pages.

Ensure `VITE_API_BASE_URL` points to the deployed backend URL.

### Backend

Deploy to Render.

Render environment variables must include:

**Infrastructure secrets (required, no defaults — must be set per-environment):**

```text
APP_ENV
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
SUPABASE_ANON_KEY
OPENAI_API_KEY
SCHEDULER_SECRET
API_ACCESS_TOKEN
FRONTEND_ORIGIN
```

**Application defaults (optional in `.env`; resolved at runtime per "Single Source of Truth"):**

```text
OPENAI_MODEL
CANDIDATE_HORIZON
MARKET_DATA_PROVIDER_KR
MARKET_DATA_PROVIDER_US
STALE_DATA_BUSINESS_DAYS
USD_KRW_RATE
```

### Database

Create Supabase project.

Run SQL migration files manually in Supabase SQL editor for MVP.

---

## README Requirements

The root README must include:

- Project overview
- Architecture diagram
- Local setup
- **Backend environment variables, presented as two groups:**
  - Infrastructure secrets (required, no defaults)
  - Application defaults (optional in `.env`; resolved via the runtime order in "Single Source of Truth")
- Frontend environment variables, with an explicit warning that `VITE_API_ACCESS_TOKEN` is a lightweight MVP gate and is visible in the frontend bundle
- Supabase setup, including a note that the service role key bypasses RLS
- Render deployment
- GitHub Pages deployment
- GitHub Actions secrets setup
- Manual report generation test
- Security warnings, including the frontend token limitation
- Single-user MVP scope warning: no login, no multi-user security, no Supabase Auth
- MVP limitations (including: no automatic trading, GitHub Actions cron drift, US DST drift, Render Free cold start, approved GDELT news context limits, free market data quality)

---

## MVP Limitations

Document these limitations clearly:

- No automatic trading
- No guaranteed profit
- Free market data may be delayed or incomplete
- AI report quality depends on input data quality
- Render Free may sleep when idle
- GitHub Actions schedule may not run exactly at the target second
- News/trend context is limited to the approved GDELT DOC 2.0 API and may be incomplete
- Single-user only: no login, no multi-user separation, no production-grade authentication
- Backtesting is basic or deferred unless explicitly implemented

---

## Completion Criteria

The MVP is complete when:

1. Backend runs locally.
2. Frontend runs locally.
3. Supabase connection works.
4. Asset CRUD works.
5. Portfolio summary works.
6. Manual domestic report generation works.
7. Manual global report generation works.
8. Reports are saved in Supabase and pass `ReportContent` validation.
9. Latest report is visible in frontend.
10. GitHub Actions workflow files exist with warm-up steps.
11. Scheduler endpoints require `SCHEDULER_SECRET` bearer token authentication.
12. All other `/api/*` endpoints require `API_ACCESS_TOKEN` bearer token authentication.
13. Rate limiting is enforced on report generation endpoints.
14. AI Provider Fallback path is implemented and tested.
15. `performance_logs` backfill runs as part of report generation.
16. `.env.example` exists with all required keys.
17. `.env` is ignored by Git.
18. Render deployment configuration (`render.yaml`) exists.
19. GitHub Pages deployment configuration exists.
20. README explains how to run, deploy, and the documented Known Limitations.
21. `pytest backend/tests -v` passes with all required test coverage from Testing Requirements.
22. `ruff check .` and `black --check .` pass with no errors.
23. README clearly states that the MVP is single-user only and not production-grade authentication.

---

## Investment Safety Requirement

All generated recommendations must be framed as decision-support information.

Do not use language that implies certainty.

Each recommendation must include:

- Action
- Confidence
- Entry or watch range
- Target price
- Stop-loss
- Reasoning
- Risk
- Invalidation condition

If the system lacks enough data, it must say so and recommend WATCH rather than fabricating a strategy.

---

## Long-Term Expansion Ideas

Do not implement these in the MVP unless explicitly requested.

Potential future phases:

- Backtesting engine
- Paper trading
- Strategy performance scoring
- Strategy weight adjustment
- News sentiment analysis
- SEC/DART filing analysis
- Sector rotation model
- Macro regime detection
- Portfolio optimization
- Broker API integration
- Push notification
- Mobile UI
- Vector DB for investment knowledge base
- Multi-agent investment committee structure
- Local LLM support
- User authentication
- Multi-user support

---

## Final Instruction for Coding Agents

Prioritize a working MVP over over-engineering, but never at the cost of omitting documented requirements.

"Avoid over-engineering" means: do not add features, libraries, services, or abstractions that are not listed in this document. It does NOT mean: skip any requirement that appears in this document, including tests, fallbacks, validation, rate limiting, and security middleware.

Build the smallest useful system that can:

1. Store the user's assets.
2. Fetch market data from pykrx (KR) and yfinance (US), with stale detection.
3. Calculate basic technical indicators from scratch (pandas/numpy only).
4. Generate AI-assisted strategy reports validated against `ReportContent`.
5. Fall back to a technical-only report when the LLM is unavailable.
6. Save reports and backfill `performance_logs` with a simple best-effort in-process implementation.
7. Show reports in a web dashboard.
8. Run scheduled report generation through GitHub Actions with cold-start warm-up.

Keep code modular so later phases can improve data quality, AI reasoning, backtesting, and portfolio optimization.

When in doubt: re-read Meta Rules for Coding Agents at the top of this document, and ask the user.
