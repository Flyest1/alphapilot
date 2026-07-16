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
6. **No trading code.** Do not create functions, classes, modules, routes, buttons, placeholders, or stubs for order placement, trade execution, or automatic trading. Broker API usage is allowed only for the explicitly approved read-only Toss Invest account/holdings sync described below.
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
Phase: Post-MVP (development plan v2)
Status: MVP complete; Track R and Post-MVP Phases 1-6, 8-9 implemented in code
Primary goal now: keep improving reliability, signal quality, and daily usability.
Phase 10 is documented in docs/phase10_multi_user_design.md but remains implementation-blocked.
Signal-quality improvement Phase 6 shadow-evaluation foundation is implemented in code; migration 016
was applied manually to the operating Supabase project on 2026-07-17. No challenger model or promotion
threshold is configured yet.
```

The detailed upgrade plan lives in `docs/development_plan_v2.md` and the code review baseline in `docs/code_review_2026_06.md`. When this file and the plan conflict, this file wins.

The MVP already includes:

- GitHub Pages React frontend
- Oracle Cloud Always Free FastAPI backend, with Render config retained as rollback
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
- persisted manual report job status with step timings
- scheduled domestic/global reports
- strategy table and candidate strategy view
- performance log backfill
- portfolio snapshots saved after report generation
- recommendation lifecycle tracking through `recommendation_cycles`
- lightweight single-user token access gate

Future work must preserve these capabilities while improving reliability and investment usefulness.

---

## Non-Negotiable Product Boundaries

AlphaPilot must not:

- place orders
- connect to broker APIs except the explicitly approved read-only Toss Invest account/holdings sync
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
- plain CSS / CSS modules
- Tailwind CSS 3.x (approved 2026-07 for frontend styling)
- GSAP 3.x (approved 2026-07 for UI motion only)
- Recharts (charting; approved in development plan v2 to replace hand-rolled SVG charts)
- GitHub Pages deployment
- `VITE_API_BASE_URL` for backend URL

Tailwind may be used for utility styling, component layers, and design tokens. GSAP may be used only for
non-essential UI transitions and must respect reduced-motion preferences. Do not use GSAP for financial
logic, report generation logic, data fetching, persistence, or any behavior that changes investment
recommendations.

Do not add MUI, Chakra, Bootstrap, Next.js, or other UI frameworks unless the user explicitly approves an AGENTS.md update.

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
- ESLint + Prettier (frontend, approved in development plan v2)
- Vitest + React Testing Library (frontend tests, approved in development plan v2)
- GitHub Actions CI workflow must run: `pytest backend/tests`, `ruff check .`, `black --check .`, frontend lint/test/build

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
- Render                      (legacy backend rollback hosting; paid tier upgrade pre-approved when a phase requires it)
- Oracle Cloud Always Free    (backend hosting replacement for Render only; Supabase remains the database unless explicitly approved later)
- Let's Encrypt               (TLS certificate issuance for the Oracle-hosted backend only)
- GitHub Pages                (frontend hosting)
- GitHub Actions              (scheduler)
- pykrx                       (KR market data)
- yfinance                    (US/ETF/FX market data)
- GDELT DOC 2.0 API           (news/trend context)
- Telegram Bot API            (notification channel, Phase 9; user must provide bot token via backend env var)
- Toss Invest Open API        (read-only account/holdings sync only; no order endpoints)
```

Toss Invest Open API exception (approved 2026-06):

- Allowed only for read-only account and holdings synchronization.
- API-linked assets must be visibly marked separately from manually entered assets.
- Manual assets must remain supported so the user can delete duplicates after sync review.
- Toss credentials must live only in backend environment variables or `.env`, never in frontend code, localStorage, Supabase, GitHub Pages, or committed files.
- Do not implement or call order create, order modify, order cancel, broker execution, automatic trading, order preview, buying-power checks for execution, sellable-quantity checks for execution, or any route/button/stub that could become a trading workflow.

2026-06 decision: the user approved paid tiers and additional services in principle.
Paid upgrades of already-allowed services (Render, Supabase, OpenAI usage) may proceed
when a roadmap phase requires them; record the change in README. Entirely new providers
(paid market data APIs, email providers, additional LLM providers, vector databases,
file storage) are allowed in principle but the specific provider and cost must be
confirmed with the user before implementation and added to this list.

Still requiring case-by-case approval before implementation:

- specific paid market data APIs
- email/push providers other than Telegram
- external cron/ping services
- alternative LLM providers
- Supabase Auth login flow (Phase 7/10 decision)

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
FRONTEND_ORIGIN=http://localhost:5173,http://127.0.0.1:5173

SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_ANON_KEY=your-anon-key

OPENAI_API_KEY=your-openai-api-key
SCHEDULER_SECRET=change-this-secret
API_ACCESS_TOKEN=change-this-user-token
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
TELEGRAM_CHAT_ID=your-telegram-chat-id
TOSS_INVEST_CLIENT_ID=your-toss-invest-client-id
TOSS_INVEST_CLIENT_SECRET=your-toss-invest-client-secret
TOSS_INVEST_ACCOUNT_ID=your-toss-invest-account-id
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
TELEGRAM_NOTIFY_REPORT_COMPLETED=false
TELEGRAM_NOTIFY_TARGET_HIT=false
TELEGRAM_NOTIFY_STOP_HIT=false
TELEGRAM_NOTIFY_CYCLE_CLOSED=false
TELEGRAM_NOTIFY_DRIFT_WARNING=false
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

Report jobs are persisted in Supabase `report_jobs`.

### Performance

```text
GET /api/performance-logs
```

### Recommendation Cycles

```text
GET /api/recommendation-cycles
```

### Notifications

```text
GET  /api/notifications
POST /api/notifications/{notification_id}/read
POST /api/notifications/read-all
```

### Signal Quality

Scheduler-protected:

```text
POST /api/candidate-universe/refresh
```

User-token protected:

```text
POST /api/backtests/rules/run
GET  /api/signal-models/evaluation
```

The signal-model evaluation endpoint is read-only and research-only. It must not expose mutation,
automatic promotion, scheduling, or trading behavior. Scheduled reports are official future shadow
samples; manual reports may store input lineage only. The evaluation window is fixed at 12 weeks.

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
    confidence_detail: Optional[dict] = None
    position_sizing: Optional[dict] = None


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
- `report_jobs`
- `portfolio_snapshots`
- `recommendation_cycles`
- `market_data_cache`
- `candidate_universe`
- `notifications`
- `signal_model_versions`
- `signal_model_assignments`
- `signal_model_evaluation_runs`
- `signal_model_evaluation_observations`
- `signal_model_report_links`

Existing additive settings columns:

- `candidate_horizon`
- `usd_krw_rate`
- target allocation, rebalance, risk-per-trade, and cost-rate columns from migration 011
- Telegram event opt-in columns from migration 013

Signal-model lineage tables are introduced by additive migration 016. It seeds the immutable current
champion only; it must not seed a challenger, evaluation run, promotion decision, or automatic workflow.

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
- call `/health` before calling the report endpoint

Known limitations to keep documented:

- GitHub Actions cron can drift or be skipped.
- Render Free can cold start when using the rollback backend.
- Oracle VM hosting avoids Render cold start, but OS security updates, process restarts, firewall rules, and TLS renewal become operator responsibilities.
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
- no decorative UI framework presets; Tailwind/GSAP usage must stay consistent with AlphaPilot's product UI

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

Status: implemented.

Goal: Make report generation observable and reliable.

Implemented baseline:

- `report_jobs` Supabase table
- persisted manual report job status
- report generation step timing
- failure reason categories safe for UI
- recent job visibility in Status page
- latest GitHub Actions schedule guidance in Status page

Do not add a separate worker, queue service, or external scheduler unless the user explicitly approves a new architecture.

### Phase 2: Portfolio Snapshots

Status: implemented.

Goal: Make dashboard history real, not inferred only from current price history.

Implemented baseline:

- `portfolio_snapshots` table
- daily portfolio total value
- daily cost basis
- cash value
- domestic/global/ETF allocation
- dashboard chart backed by snapshots

Decision: snapshots are saved when report generation completes. If fewer than two snapshots exist, dashboard history may fall back to market-data-derived history.

### Phase 3: Recommendation Lifecycle Tracking

Status: implemented.

Goal: Track whether recommendations are useful over time.

Implemented baseline:

- `recommendation_cycles` table
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

- Repeated same ticker/horizon/action does not reset an active cycle.
- A new cycle starts when action changes, target/stop changes by at least 5%, horizon changes, or the prior cycle is closed.
- Current `performance_logs` remains preserved and runs in parallel.

### Phase R (Track R): Structural Refactoring and Quality Infrastructure

Status: implemented (2026-06).

Goal: Remove structural debt before feature expansion. Behavior-preserving; public API contracts unchanged.

Implement:

- split `backend/app/services/report_service.py` into `report/` package: pipeline orchestration, candidate screener, prompt builder, persistence, tracking (performance/cycle backfill)
- single `app/utils/tickers.py` (normalize/infer market) and `app/utils/labels.py` (Korean labels); remove duplicates
- backfill efficiency: query only unevaluated rows; reuse price history per ticker
- persist intraday market data cache in Supabase (`market_data_cache`, additive migration)
- replace plain token comparison with `secrets.compare_digest`
- frontend: shared `src/utils/formatters.js`; split `Reports.jsx` and `Dashboard.jsx` into sub-components; ErrorBoundary, retry, skeleton loaders; API client timeout/cold-start retry; UI strings to constants module (no i18n library)
- frontend tooling: ESLint, Prettier, Vitest + React Testing Library
- replace hand-rolled SVG/CSS charts with Recharts
- add `.github/workflows/ci.yml` running backend and frontend checks

### Phase 4: Analysis Quality and Performance Feedback

Status: implemented (2026-06). Migrations 009 (sector columns) and 010 (report_inputs) required.

Goal: Feed accumulated `recommendation_cycles` outcomes back into confidence and transparency.

Implement:

- `GET /api/recommendation-stats`: win rate, average 5d/20d returns, sample size by action x horizon x score band
- new frontend performance-analysis view for those stats
- calibrated confidence: blend technical score with measured win rate once a band has >= 30 samples; otherwise keep current score and show an "uncalibrated (low sample)" badge
- confidence explanation breakdown (technical/news/history contributions)
- sector/country/currency exposure summary (`sector` column on assets/candidates, additive; filled from yfinance info / pykrx sectors)
- concentration risk warnings (single asset >= 25%, single sector >= 40%, thresholds configurable)
- data-quality badges (freshness, provider, news availability)
- input snapshot stored with each report (`report_inputs` JSONB, additive)

Do not add new data providers without approval.

### Phase 5: Portfolio Decision Support

Status: implemented (2026-06) except sell/reduce condition checklist, which is folded into the
Phase 6 action briefing. Migration 011 (allocation/cost settings columns) required.

Goal: Move from reports to actionable portfolio management without execution.

Implement:

- ATR(14)-based stop-loss/target in `StrategyService` (replace fixed percentages; ATR implemented from scratch in `technical_analysis_service.py`)
- target allocation settings (domestic/global/cash %, per-asset cap; additive `settings` columns)
- rebalance drift card and suggestions (threshold default 5 percentage points); drift context passed to the LLM
- cash deployment suggestions
- position sizing guidance as decision support only: fixed-fractional amount ranges, never share counts or order tickets
- fee/tax-aware return estimates (commission, KR transaction tax, FX spread from settings)
- sell/reduce watchlist and condition-based checklist

Forbidden:

- order tickets
- order preview
- broker linking
- trade execution
- automatic rebalance

### Phase 6: UX and Mobile Polish

Status: implemented (2026-06). The service worker caches static assets only; offline last-report
viewing relies on the existing localStorage API cache (tokens never enter SW caches).

Goal: Make daily use comfortable on mobile.

Implement:

- "today's actions" briefing card on dashboard (stop/target hits, drift warnings, new BUY candidates, stale data)
- report diff view versus the previous report (action changes, confidence changes, added/removed candidates)
- mobile-first report cards with sorting
- faster cached first paint
- improved empty/loading/error states
- PWA install support (manifest + service worker caching static assets and the latest report; no external services)
- CSV import/export for assets

Web Push or any external notification channel requires approval (see Phase 9).

### Phase 7: Security Upgrade

Goal: Improve access control if the user decides AlphaPilot should be less exposed.

Requires user decision:

- token gate
- server-side password/session (recommended if staying single-user)
- Supabase Auth (choose this directly if Phase 10 multi-user is intended)

Do not implement until selected.

### Phase 8: Signal Quality Engine

Status: implemented (2026-06). Migration 012 (candidate_universe) required.

Goal: Improve the quality of candidate screening and validate strategy rules with evidence.

Implement:

- move hardcoded `CANDIDATE_UNIVERSE` to a `candidate_universe` table (seed migration); periodic refresh job from pykrx market-cap ranks and major yfinance ETFs (no new external services)
- offline rule backtest service validating score-to-action rules on historical prices; results shown in the performance-analysis view, clearly labeled as simulation, never as execution
- dividend/earnings calendar for owned assets within yfinance capabilities, surfaced in report risks/opportunities and dashboard

### Phase 9: Notification Center

Status: implemented (2026-06). Migration 013 (notifications and Telegram opt-in settings)
required.

Goal: Surface important events without requiring the user to open every report.

Implement:

- `notifications` table (additive): report completed, target/stop hit, cycle closed, drift warning; populated during scheduled report generation
- in-app notification badge and list with read state
- Telegram Bot API delivery for the same events (approved 2026-06): backend env vars `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, opt-in per event type in settings, graceful no-op when unset

Other external channels (email, Web Push) still require provider-specific approval before implementation.

### Phase 10 (Optional): Multi-User / Commercialization

Status: design documented only in `docs/phase10_multi_user_design.md`; no implementation.

Goal: Convert AlphaPilot into a multi-user (potentially paid) service. Design-only until explicitly approved.

Requires before any implementation:

- explicit user approval and a major AGENTS.md revision
- security model C (Supabase Auth), `user_id` on all tables, RLS
- hosting/cost plan (Render paid tier, per-user OpenAI budget caps)
- legal review of Korean investment-advisory regulation

Do not implement any part of this phase without approval.

---

## Post-MVP Development Order

Follow this order unless the user explicitly changes priority:

1. Update AGENTS.md and roadmap document. Done.
2. Persist manual report jobs in Supabase. Done.
3. Add report generation step timing and status UI. Done.
4. Add portfolio snapshots. Done.
5. Replace dashboard history with snapshot-backed history. Done.
6. Design and implement recommendation lifecycle tracking. Done.
7. Track R refactoring: backend report package split, shared utils, frontend component split, ESLint/Prettier/Vitest, Recharts, CI workflow.
8. Phase 4: recommendation stats API/view, calibrated confidence, exposure/concentration analysis, data-quality badges.
9. Phase 5: ATR-based risk levels, target allocation and rebalance drift, position sizing guidance, fee/tax-aware returns.
10. Phase 6: today's-actions briefing, report diff view, mobile cards, PWA, CSV import/export.
11. Phase 8: candidate universe table and refresh, rule backtest service, dividend/earnings calendar.
12. Phase 9: in-app notification center.
13. Decide and implement stronger security (Phase 7) if approved; Phase 10 only with explicit approval.

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

Frontend (once Track R tooling lands): Vitest + React Testing Library tests are required for shared formatters, the API client, and any component containing filtering/sorting/calculation logic. UI-only presentational components may be excluded.

---

## Deployment Rules

Frontend:

- GitHub Pages
- GitHub Actions Pages workflow
- `VITE_API_BASE_URL` secret points to the active backend host
- GitHub Pages production builds must use an HTTPS backend URL to avoid browser mixed-content blocking

Backend:

- Oracle Cloud Always Free VM is approved as the active backend host replacing Render
- Supabase remains the database; do not migrate database storage to Oracle without explicit approval
- `deploy/oracle/` contains the Oracle VM systemd/nginx deployment files
- `render.yaml` remains as a legacy rollback config
- required secrets must be set in the Oracle VM environment file, never committed

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
- Oracle Cloud Always Free backend deployment
- Render rollback notes
- GitHub Pages deployment
- GitHub Actions scheduler setup
- manual report generation behavior
- security scope
- single-user limitation
- no automatic trading
- GitHub Actions cron drift
- Render rollback cold start
- Oracle VM operation and TLS renewal responsibilities
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
