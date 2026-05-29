# AlphaPilot

AlphaPilot은 개인 자산을 등록하고, 국내/글로벌 시장 데이터와 기술 지표를 기반으로 AI 투자 전략 리포트를 생성하는 단일 사용자용 MVP입니다.

자동 매매, 주문 실행, 브로커 API 연결은 포함하지 않습니다. 모든 리포트는 투자 의사결정 지원용이며 수익을 보장하지 않습니다.

## 구성

```text
Frontend: GitHub Pages + React + Vite
Backend: Render Free + FastAPI
Database: Supabase PostgreSQL
Scheduler: GitHub Actions
AI: OpenAI API
Market Data: pykrx, yfinance
News/Trend Context: GDELT DOC 2.0 API
```

## 사용 방법

1. GitHub Pages 주소에 접속합니다.
2. 첫 화면에 Render 환경변수 `API_ACCESS_TOKEN` 값을 입력합니다.
3. `자산` 화면에서 보유 종목을 추가합니다.
4. `설정` 화면에서 AI 모델, 위험 성향, 추가 매수 후보 목표 기간, USD-KRW 환율을 조정합니다.
5. `설정` 화면에서 보유 외 추가 매수 후보군을 직접 추가하거나 비활성화합니다.
6. `상태` 화면에서 백엔드, Supabase, OpenAI 설정과 최근 리포트 상태를 확인합니다.
7. `리포트` 화면에서 국내/글로벌 리포트를 수동 생성하거나, GitHub Actions 정기 실행 결과를 확인합니다.
8. `성과 추적`은 리포트 생성 이후 1일, 5일, 20일 가격 데이터가 쌓이면 표시됩니다.

대시보드 총액은 KRW 기준입니다. USD 주식, 미국 ETF, USD 현금은 `설정`의 USD-KRW 환율로 환산합니다. 리포트 생성 시 yfinance의 `KRW=X` 최신 값을 가져올 수 있으면 해당 환율이 설정에 반영되고, 실패하면 기존 설정값을 그대로 사용합니다.

CASH 자산은 `수량 × 평균 매입가`로 계산됩니다. 현금 총액을 한 번에 넣으려면 수량은 `1`, 평균 매입가는 현금 총액으로 입력하세요. 수량을 `0`으로 입력하면 평가금액도 `0`으로 계산됩니다.

미국 주식 티커에 점이 들어가는 경우(예: `BRK.B`)는 그대로 입력해도 됩니다. 백엔드는 yfinance 조회 시 필요한 `BRK-B` 형식으로 자동 변환합니다.

대시보드는 최신 종가와 직전 거래일 종가 차이로 1일 자산 변동을 계산합니다. 별도의 일자별 포트폴리오 스냅샷 테이블은 아직 없으므로, 과거 장기 추이는 성과 추적 로그와 최신 시세 기준으로만 표시됩니다.

추가 매수 후보 목표 기간은 다음 기준으로 동작합니다.

```text
short  = 약 5거래일 목표
medium = 약 20거래일 목표
long   = 약 60거래일 목표
```

## 로컬 실행

백엔드:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

프론트엔드:

```powershell
cd frontend
npm install
npm run dev
```

Supabase 설정이 없으면 백엔드는 로컬 메모리 저장소로 실행됩니다. 실제 배포 환경에서는 Supabase 설정이 필요합니다.

## 백엔드 환경변수

Render 또는 로컬 `backend/.env`에 설정합니다. 실제 키는 커밋하지 마세요.

```text
APP_ENV=development
FRONTEND_ORIGIN=http://localhost:5173

SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_ANON_KEY=your-anon-key

OPENAI_API_KEY=your-openai-api-key
SCHEDULER_SECRET=change-this-secret
API_ACCESS_TOKEN=change-this-user-token

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

애플리케이션 기본값은 `settings` 테이블 값을 우선 사용하고, 값이 없으면 `.env`, 그 다음 Pydantic 기본값을 사용합니다.

## 프론트엔드 환경변수

GitHub Pages 빌드에는 API 주소만 필요합니다.

```text
VITE_API_BASE_URL=https://alphapilot-backend.onrender.com
```

`API_ACCESS_TOKEN`은 프론트엔드 번들에 넣지 않습니다. 접속자가 화면에서 직접 입력하고 브라우저 `localStorage`에 저장합니다.

주의: `localStorage` 저장 방식은 개인용 MVP 편의 기능입니다. XSS에 취약할 수 있으므로 다중 사용자 또는 공개 서비스 수준의 인증으로 간주하지 마세요.

## Supabase 설정

신규 프로젝트라면 Supabase SQL Editor에서 아래 파일 내용을 실행합니다.

```text
backend/app/db/migrations/001_initial_schema.sql
```

기존 프로젝트라면 추가 매수 후보 목표 기간 컬럼을 위해 아래 파일도 실행합니다.

```text
backend/app/db/migrations/002_add_candidate_horizon.sql
```

실행 SQL:

```sql
alter table settings
add column if not exists candidate_horizon text default 'medium';
```

후보군 관리 기능을 사용하려면 아래 파일도 실행합니다.

```text
backend/app/db/migrations/003_create_candidate_assets.sql
```

실행 SQL:

```sql
create table if not exists candidate_assets (
  id uuid primary key default gen_random_uuid(),
  market text not null,
  ticker text not null,
  name text not null,
  currency text default 'KRW',
  memo text,
  is_active boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
```

USD-KRW 환율 설정을 사용하려면 아래 파일도 실행합니다.

```text
backend/app/db/migrations/004_add_usd_krw_rate.sql
```

실행 SQL:

```sql
alter table settings
add column if not exists usd_krw_rate numeric default 1400;
```

Supabase service role key는 RLS를 우회합니다. 반드시 백엔드 서버 환경변수에만 보관하고, 프론트엔드나 에러 메시지에 노출하지 마세요.

## Render 배포

백엔드는 Render Free에 배포합니다. Render 환경변수에는 최소 아래 값이 필요합니다.

```text
APP_ENV=production
FRONTEND_ORIGIN=https://flyest1.github.io
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
SUPABASE_ANON_KEY
OPENAI_API_KEY
SCHEDULER_SECRET
API_ACCESS_TOKEN
```

Render Free는 유휴 상태 후 cold start가 발생할 수 있습니다. GitHub Actions는 리포트 생성 전에 `/health`를 호출해 백엔드를 깨웁니다.

## GitHub Pages 배포

GitHub repository secrets에 아래 값을 설정합니다.

```text
VITE_API_BASE_URL=https://alphapilot-backend.onrender.com
```

`VITE_API_ACCESS_TOKEN`은 더 이상 사용하지 않습니다. 기존에 등록되어 있어도 코드에서 읽지 않으며, 삭제해도 됩니다.

## GitHub Actions 스케줄러

GitHub repository secrets에 아래 값을 설정합니다.

```text
BACKEND_URL=https://alphapilot-backend.onrender.com
SCHEDULER_SECRET=Render에 설정한 SCHEDULER_SECRET과 같은 값
```

국내 리포트:

```text
30 23 * * 0-4
```

글로벌 리포트:

```text
30 13 * * 1-5
```

GitHub Actions 예약 실행은 best-effort입니다. GitHub 부하에 따라 몇 분에서 수십 분 지연될 수 있습니다. 글로벌 리포트 cron은 고정 `13:30 UTC`이며, 미국 서머타임을 자동 보정하지 않습니다.

## 수동 리포트 생성

프론트엔드 `리포트` 화면에서 국내/글로벌 리포트를 직접 생성할 수 있습니다. 수동 생성 API는 `API_ACCESS_TOKEN`으로 보호됩니다.

보유 외 추가 매수 후보는 `설정` 화면의 후보군 목록을 우선 사용합니다. 직접 등록한 활성 후보가 없으면 앱에 포함된 기본 후보군을 사용합니다.

## 뉴스/동향 반영

리포트 생성 시 GDELT DOC 2.0 API에서 최근 3일 뉴스/동향 헤드라인을 조회해 AI 분석 컨텍스트로 전달합니다. 별도 뉴스 섹션을 화면에 만들지는 않고, 관련성이 있을 때만 시장 요약, 위험 요인, 기회 요인, 종목별 판단 근거에 반영합니다.

GDELT는 무료/무키 기반의 글로벌 뉴스 검색 API입니다. 제공자 장애, 검색 누락, 언어/출처 편향이 있을 수 있으며, 뉴스 조회 실패가 리포트 생성을 막지는 않습니다.

스케줄러용 엔드포인트는 계속 `SCHEDULER_SECRET`을 사용합니다.

```powershell
curl -X POST "$env:BACKEND_URL/api/reports/domestic/generate" `
  -H "Authorization: Bearer $env:SCHEDULER_SECRET"
```

리포트 생성 엔드포인트는 OpenAI 비용 보호를 위해 엔드포인트별 하루 10회로 제한됩니다.

## 보안 범위

이 MVP는 단일 사용자용입니다. Supabase Auth, 로그인/회원가입, 사용자별 권한 분리는 구현하지 않았습니다.

현재 보안 방식은 다음과 같습니다.

- 모든 `/api/*` 요청은 토큰이 필요합니다.
- 정기 리포트 생성 엔드포인트는 `SCHEDULER_SECRET`을 사용합니다.
- 일반 API와 수동 리포트 생성은 `API_ACCESS_TOKEN`을 사용합니다.
- 두 값은 반드시 서로 다르게 설정하세요. 같게 설정하면 스케줄러 시크릿으로 일반 API까지 호출할 수 있습니다.
- GitHub Pages 정적 URL 자체는 public일 수 있지만, 토큰 없이는 백엔드 데이터 API를 호출할 수 없습니다.

주의: `API_ACCESS_TOKEN`이 유출되면 해당 토큰을 가진 사람이 자산과 리포트 데이터에 접근할 수 있습니다. 이 방식은 production-grade 인증이 아니라 단일 사용자 MVP용 접근 게이트입니다.

## 제한 사항

- 자동 매매와 주문 실행 없음
- 수익 보장 없음
- 뉴스/동향 컨텍스트는 GDELT DOC 2.0 API에 한정되며 누락될 수 있음
- pykrx/yfinance 데이터는 지연되거나 실패할 수 있음
- Render Free cold start 가능
- GitHub Actions 예약 실행 지연 가능
- 글로벌 리포트 cron은 미국 서머타임 자동 보정 없음
- 추가 매수 후보군은 직접 등록한 후보군 또는 MVP용 기본 후보군을 사용하며, 외부 스크리닝 API를 사용하지 않음

## 검증 명령

```powershell
pytest backend/tests -v
ruff check .
black --check .
cd frontend
npm run build
```
