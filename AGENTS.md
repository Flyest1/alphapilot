# AGENTS.md

## Purpose

This file is the single source of truth for AlphaPilot after MVP completion.

AlphaPilot is a single-user personal AI investment decision-support system. The MVP is implemented and deployed with free infrastructure. Future work must improve reliability, data quality, portfolio intelligence, and user experience without adding automatic trading or broker execution.

The product should act like a personal CIO / investment strategist:

```text
Return optimization = expected return * probability of success - downside risk - volatility risk - concentration risk - liquidity risk
```

All recommendations are decision-support information only. They must never imply guaranteed profit or execute trades.

---

## Meta Rules for Coding Agents

1. **This document is the single source of truth.** Do not infer, extrapolate, or add product requirements not stated here.
2. **Ask only when ambiguity blocks implementation.** If ambiguity affects architecture, security, external services, database schema, Pydantic models, or public API contracts, stop and ask the user.
3. **Whitelist enforcement.** Do not introduce libraries, external services, hosting providers, API providers, scraping methods, schedulers, or UI frameworks that are not explicitly allowed here.
4. **No silent omission.** If a documented requirement cannot be implemented in the current environment, state it clearly and keep the implementation locally testable with mocks where appropriate.
5. **Code-as-spec wins over prose.** Pydantic models, SQL schemas, public API contracts, and JSON examples in this document are authoritative.
6. **No trading code.** Do not create functions, classes, modules, routes, buttons, placeholders, or stubs for broker APIs, order placement, trade execution, or automatic trading.
7. **Commit discipline.** Use Conventional Commits. Keep commits scoped to the current roadmap step.
8. **Test before commit.** Code changes must pass:

```powershell
pytest backend/tests -v
ruff check .
black --check .
```

Frontend changes must also pass:

```powershell
cd frontend
npm run build
```

9. **Protect existing user data.** Supabase migrations must be additive unless the user explicitly approves destructive migration.
10. **README language.** User-facing README content must remain Korean unless the user requests otherwise.

---

## Current Product Phase

```text
Phase: Post-MVP
Status: MVP complete, deployed, and usable
Primary goal now: turn the MVP into a reliable personal investment operating system
```

The MVP already includes:

- GitHub Pages React frontend
- Render Free FastAPI backend
- Supabase PostgreSQL persistence
- GitHub Actions scheduled report calls
- OpenAI structured report generation
- technical-only report fallback
- pykrx and yfinance market data
- GDELT DOC 2.0 news/trend context
- asset CRUD
- candidate asset management
- settings management
- portfolio summary
- dashboard charts
- manual report generation
- scheduled domestic/global reports
- strategy table and candidate strategy view
- performance log backfill
- lightweight single-user token access gate

Future work must preserve these capabilities while improving reliability and investment usefulness.

---

## Non-Negotiable Product Boundaries

AlphaPilot must not:

- place orders
- connect to broker APIs
- implement paper trading as if it were execution
- create trade execution stubs
- promise guaranteed profit
- imply risk-free returns
- expose OpenAI keys, Supabase keys, scheduler secrets, or database credentials to the frontend
- add unapproved external services
- scrape websites with browsers or HTML scraping

Allowed recommendation language:

- consider
- candidate
- watch
- risk-managed entry
- partial buy
- reduce exposure
- stop-loss
- invalidation condition

Forbidden recommendation language:

- guaranteed profit
- certain return
- risk-free
- must buy
- must sell

---

## Required Technology Stack

### Frontend

- React 18.x
- Vite 5.x
- plain CSS / CSS modules only
- GitHub Pages deployment
- `VITE_API_BASE_URL` for backend URL

Do not add Tailwind, MUI, Chakra, Bootstrap, Next.js, or other UI frameworks unless the user explicitly approves an AGENTS.md update.

### Backend

- Python 3.10
- FastAPI
- Uvicorn
- supabase-py
- openai Python SDK v1.x
- pandas
- numpy
- pykrx
- yfinance
- pydantic v2.x
- tenacity
- python-dotenv

### Code Quality

- ruff
- black, line length 100
- pytest

### Forbidden Technical Analysis Libraries

Do not use:

- `ta`
- `pandas-ta`
- `TA-Lib`
- `finta`
- any other technical-analysis library

All technical indicators must be implemented from scratch using pandas and numpy in `backend/app/services/technical_analysis_service.py`.

---

## Allowed External Services

Only these external services are allowed:

```text
- OpenAI API                  (LLM)
- Supabase                    (database, auth-disabled unless explicitly approved later)
- Render                      (backend hosting, Free tier for current deployment)
- GitHub Pages                (frontend hosting)
- GitHub Actions              (scheduler)
- pykrx                       (KR market data)
- yfinance                    (US/ETF/FX market data)
- GDELT DOC 2.0 API           (news/trend context)
```

Any new service requires explicit user approval and an AGENTS.md update before implementation.

Examples requiring approval:

- paid market data APIs
- email providers
- push notification providers
- Telegram/Discord/Slack bots
- external cron/ping services
- vector databases
- alternative LLM providers
- Supabase Auth login flow
- file-storage services

---

## Security Model

### Current Security

AlphaPilot remains single-user.

Current access control:

- Scheduler endpoints use `SCHEDULER_SECRET`.
- Normal API endpoints use `API_ACCESS_TOKEN`.
- The frontend asks the user to enter `API_ACCESS_TOKEN` and stores it in browser `localStorage`.
- `API_ACCESS_TOKEN` is not embedded in the frontend bundle.
- Supabase service role key is server-side only.

This is an MVP access gate, not production-grade authentication.

### Security Rules

1. Never commit `.env`.
2. Keep `.env` ignored by Git.
3. Never expose OpenAI keys, Supabase keys, or `SCHEDULER_SECRET` to frontend code.
4. CORS must allow only configured frontend origins.
5. API token and scheduler secret must be different values.
6. Do not add login/signup, user tables, `user_id`, or multi-user permissions unless the user explicitly approves the security model change.

### Future Security Decision

Before implementing stronger authentication, stop and ask the user to choose one:

```text
A. Keep single-user token gate
B. Add server-side password/session gate
C. Use Supabase Auth
```

Choice C requires AGENTS.md update because MVP explicitly avoided Supabase Auth and multi-user flows.

---

## Environment Variables

### Backend Infrastructure Secrets

These live only in `.env` or hosting environment variables:

```env
APP_ENV=development
FRONTEND_ORIGIN=http://localhost:5173

SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_ANON_KEY=your-anon-key

OPENAI_API_KEY=your-openai-api-key
SCHEDULER_SECRET=change-this-secret
API_ACCESS_TOKEN=change-this-user-token
```

### Application Defaults

These may exist in `.env.example`, SQL defaults, and Pydantic settings models:

```env
DOMESTIC_REPORT_TIME=08:30
GLOBAL_REPORT_TIME=22:30
AI_PROVIDER=openai
OPENAI_MODEL=gpt-5.4-mini
RISK_PROFILE=balanced
CANDIDATE_HORIZON=medium
FRONTEND_TIMEZONE=Asia/Seoul
MARKET_DATA_PROVIDER_KR=pykrx
MARKET_DATA_PROVIDER_US=yfinance
STALE_DATA_BUSINESS_DAYS=2
USD_KRW_RATE=1400
```

Runtime resolution order:

1. Supabase `settings` table row
2. `.env` value
3. Pydantic default

When changing an application default, update all relevant locations and add/update tests for consistency.

### Frontend

```env
VITE_API_BASE_URL=http://localhost:8000
```

Do not use `VITE_API_ACCESS_TOKEN` in the current implementation. The access token is entered by the user at runtime.

---

## Current Public API Contracts

### Health

```text
GET /health
```

### Assets

```text
GET    /api/assets
POST   /api/assets
PUT    /api/assets/{asset_id}
DELETE /api/assets/{asset_id}
```

Supported markets:

```text
KR
US
ETF
CASH
```

### Candidate Assets

```text
GET    /api/candidates
POST   /api/candidates
PUT    /api/candidates/{candidate_id}
DELETE /api/candidates/{candidate_id}
```

### Portfolio

```text
GET /api/portfolio/summary
```

Must include:

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
value_history
latest_report_summary
```

### Reports

Scheduler-protected:

```text
POST /api/reports/domestic/generate
POST /api/reports/global/generate
```

User-token protected:

```text
POST /api/reports/domestic/manual-generate
POST /api/reports/global/manual-generate
GET  /api/reports/manual-jobs/{job_id}
GET  /api/reports/latest
GET  /api/reports
GET  /api/reports/{report_id}
```

Manual report generation must be asynchronous from the frontend perspective:

- return a job id quickly
- keep existing reports visible
- poll job status
- refresh latest report after completion

The current job store is in process memory. Future work should persist report jobs in Supabase.

### Performance

```text
GET /api/performance-logs
```

### Settings

```text
GET  /api/settings
POST /api/settings
```

### System Status

```text
GET /api/system/status
```

---

## Authoritative Report Models

The stored report JSON must validate against `ReportContent`.

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict


class AssetStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    name: str
    current_price: Optional[float] = None
    action: Literal["BUY", "HOLD", "REDUCE", "SELL", "WATCH"]
    confidence: int = Field(ge=0, le=100)
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


class PortfolioSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_market_value: float
    total_return_rate: float
    risk_level: Literal["low", "medium", "high"]
    allocation_comment: str


class ReportContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_type: Literal["domestic", "global"]
    generated_at: str
    market_summary: MarketSummary
    portfolio_summary: PortfolioSummary
    key_risks: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    asset_strategies: list[AssetStrategy] = Field(default_factory=list)
    disclaimer: str
```

Do not add fields to this schema without explicit approval. If news/trend information is used, fold it into `summary`, `macro_factors`, `key_risks`, `opportunities`, `reasoning`, or `risk`.

---

## Current Database Baseline

Existing Supabase tables:

- `assets`
- `reports`
- `strategies`
- `settings`
- `performance_logs`
- `candidate_assets`

Existing additive settings columns:

- `candidate_horizon`
- `usd_krw_rate`

Do not alter or remove existing columns without explicit approval. New tables must be introduced through migration files under:

```text
backend/app/db/migrations/
```

---

## Market Data Rules

Provider routing:

- `KR`: pykrx
- `US`: yfinance
- `ETF`: yfinance unless it is a KR ticker explicitly handled as KR
- `CASH`: no market data fetch

Market data result must include:

```text
provider
last_trading_date
is_stale
data_quality_note
```

Stale data threshold:

```text
business_days_since(last_trading_close, now_in_market_timezone) > stale_data_business_days
```

If data is stale or unavailable:

```text
action = WATCH
confidence = 0
reasoning = "data-limited"
```

Do not fabricate current prices.

---

## Technical Analysis Requirements

Maintain these indicators:

```text
SMA 5
SMA 20
SMA 60
SMA 120
EMA 12
EMA 26
RSI 14
MACD 12/26/9
MACD signal
Bollinger Band 20, 2 sigma
Volume change rate, 5-day MA vs 20-day MA
20-day high/low
Trend score
```

Technical score must remain 0-100 with this weighting unless explicitly approved:

```text
Trend:          30
Momentum:       25
Volume:         15
Volatility:     15
Price position: 15
```

Score interpretation:

```text
80-100: strong bullish setup
65-79:  bullish but needs confirmation
50-64:  neutral / watch
35-49:  weak / reduce risk
0-34:   bearish / sell or avoid
```

---

## Strategy Actions

Only these action values are allowed:

```text
BUY
HOLD
REDUCE
SELL
WATCH
```

For non-owned candidate ideas:

- `BUY` means risk-managed new entry candidate.
- `WATCH` means attractive enough to monitor but not yet an entry.
- Avoid `HOLD` for non-owned candidates in user-facing output.

Each strategy must include:

- action
- confidence
- entry or watch range
- target price
- stop-loss
- reasoning
- risk
- invalidation condition

---

## AI Report Generation

OpenAI is the default AI provider.

Model selection:

1. `settings.ai_model`
2. `OPENAI_MODEL`
3. Pydantic default

Current default:

```text
gpt-5.4-mini
```

Fallback:

- If OpenAI fails after retries, generate a technical-only report.
- If OpenAI output fails Pydantic validation twice, generate a technical-only report.
- Technical-only confidence is capped at 60.
- Add `"AI reasoning unavailable for this report"` to `key_risks`.

Do not call a different AI provider unless explicitly approved and added to this file.

---

## Scheduler Requirements

Use GitHub Actions only.

Domestic report:

```text
08:30 KST = 23:30 UTC previous day
cron: "30 23 * * 0-4"
```

Global report:

```text
22:30 KST = 13:30 UTC
cron: "30 13 * * 1-5"
```

Workflows must:

- support `workflow_dispatch`
- use `BACKEND_URL` and `SCHEDULER_SECRET` GitHub Secrets
- warm up Render via `/health` before calling the report endpoint

Known limitations to keep documented:

- GitHub Actions cron can drift or be skipped.
- Render Free can cold start.
- Global report cron does not auto-adjust for US daylight saving time.

Do not add external ping or cron services without explicit approval.

---

## Frontend Product Requirements

Maintain these pages:

- Dashboard
- Assets
- Reports
- Settings
- Status

Frontend priorities:

- mobile-friendly layout
- readable Korean UI
- compact strategy summaries
- expandable details
- visible risk controls
- clear loading, background refresh, and generation status
- no decorative UI frameworks

Dashboard must show:

- total portfolio value in KRW
- total profit/loss
- total return rate
- domestic/global/cash allocation
- asset allocation
- 1-day change
- daily value/profit chart
- latest report summary
- top opportunities
- key risks

Reports must show:

- latest domestic/global report
- historical report list with pagination or collapsed list
- owned strategies
- additional candidate strategies
- strategy action
- confidence
- buy/watch range
- target price
- stop loss
- period returns when available
- performance tracking

---

## Post-MVP Roadmap

### Phase 1: Operational Reliability

Goal: Make report generation observable and reliable.

Implement:

- `report_jobs` Supabase table
- persisted manual report job status
- report generation step timing
- failure reason categories safe for UI
- retry visibility in Status page
- latest GitHub Actions schedule guidance in Status page

Do not add a separate worker, queue service, or external scheduler. Keep jobs in the Render/FastAPI process unless the user explicitly approves a new architecture.

### Phase 2: Portfolio Snapshots

Goal: Make dashboard history real, not inferred only from current price history.

Implement:

- `portfolio_snapshots` table
- daily portfolio total value
- daily cost basis
- cash value
- domestic/global/ETF allocation
- per-asset snapshot rows if needed
- dashboard chart backed by snapshots

Open question before implementation:

- Should snapshots be created only when reports run, or also when the user opens the dashboard?

Ask before implementing if this affects schema or schedule.

### Phase 3: Recommendation Lifecycle Tracking

Goal: Track whether recommendations are useful over time.

Implement:

- recommendation lifecycle table, tentatively `recommendation_cycles`
- start date
- ticker
- report type
- action
- target horizon
- entry/reference price
- target price
- stop loss
- status: active, hit_target, hit_stop, expired, superseded
- 1d/5d/20d/60d returns

Rules:

- Repeated same ticker/action must not reset an active cycle.
- A new cycle starts only when the recommendation materially changes or prior cycle is closed.
- Preserve current `performance_logs` until migration path is explicitly implemented.

Ask before implementing final schema.

### Phase 4: Analysis Quality

Goal: Improve the usefulness and transparency of recommendations.

Implement:

- clearer confidence explanation
- technical/news/portfolio contribution breakdown
- candidate horizon-specific scoring display
- sector/country/currency exposure summary
- concentration risk warnings
- data-quality badges
- input snapshot stored with each report if schema is approved

Do not add new data providers without approval.

### Phase 5: Portfolio Decision Support

Goal: Move from reports to actionable portfolio management without execution.

Potential features:

- target allocation settings
- rebalance suggestions
- cash deployment suggestions
- sell/reduce watchlist
- position sizing guidance as decision support only
- condition-based checklist

Forbidden:

- order tickets
- order preview
- broker linking
- trade execution
- automatic rebalance

### Phase 6: UX and Mobile Polish

Goal: Make daily use comfortable on mobile.

Implement:

- mobile-first report cards
- dashboard quick summary
- faster cached first paint
- improved empty/loading/error states
- PWA install support if it does not require new services

Notifications require approval because they may introduce external services.

### Phase 7: Security Upgrade

Goal: Improve access control if the user decides AlphaPilot should be less exposed.

Requires user decision:

- token gate
- server-side password/session
- Supabase Auth

Do not implement until selected.

---

## Post-MVP Development Order

Follow this order unless the user explicitly changes priority:

1. Update AGENTS.md and roadmap document.
2. Persist manual report jobs in Supabase.
3. Add report generation step timing and status UI.
4. Add portfolio snapshots.
5. Replace dashboard history with snapshot-backed history.
6. Design and implement recommendation lifecycle tracking.
7. Migrate or bridge existing `performance_logs`.
8. Add confidence explanation and data-quality transparency.
9. Add portfolio decision-support features.
10. Improve mobile UX.
11. Decide and implement stronger security if approved.

Each step must include:

- focused implementation
- tests for service/API changes
- README update when setup, behavior, or limitations change
- Conventional Commit
- push after successful checks if deployment is expected

---

## Testing Requirements

Backend service modules must have pytest coverage with external calls mocked.

Minimum coverage to preserve:

- auth middleware
- asset CRUD
- candidate asset CRUD
- settings defaults
- portfolio summary
- market data routing and stale handling
- technical indicators
- OpenAI structured output
- AI validation retry
- technical-only fallback
- strategy generation
- report generation
- manual report job status
- performance tracking/backfill
- system status
- rate limiting

New post-MVP modules must add tests in `backend/tests/`.

---

## Deployment Rules

Frontend:

- GitHub Pages
- GitHub Actions Pages workflow
- `VITE_API_BASE_URL` secret points to Render backend

Backend:

- Render Free unless the user approves a hosting change
- `render.yaml` remains the deployment config
- required secrets must be set in Render environment variables

Database:

- Supabase Free PostgreSQL
- migrations are run manually through SQL Editor for MVP/post-MVP unless a migration runner is explicitly approved

Scheduler:

- GitHub Actions scheduled workflows
- no external cron/ping service

---

## README Requirements

README must document:

- Korean usage instructions
- architecture
- local setup
- backend environment variables
- frontend environment variables
- Supabase setup and service-role risk
- Render deployment
- GitHub Pages deployment
- GitHub Actions scheduler setup
- manual report generation behavior
- security scope
- single-user limitation
- no automatic trading
- GitHub Actions cron drift
- Render cold start
- GDELT limitations
- free market data limitations
- any new migration files

---

## Completion Definition for Post-MVP Steps

A post-MVP step is complete when:

1. The requested behavior works locally or is mocked if external setup is required.
2. Tests are added or updated.
3. Required commands pass.
4. README or setup instructions are updated if needed.
5. No unapproved external services or libraries were added.
6. No trading/execution code was introduced.
7. Changes are committed with a Conventional Commit.
8. Deployment changes are pushed when the user expects the hosted site to update.
