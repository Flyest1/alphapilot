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

대시보드는 최신 종가와 직전 거래일 종가 차이로 1일 자산 변동을 계산합니다. 리포트 생성 또는 `자산 스냅샷 저장` 버튼으로 저장된 포트폴리오 스냅샷이 2개 이상 있으면 장기 추이는 스냅샷 기준으로 표시됩니다.

대시보드 차트는 보유 자산의 최근 가격 이력으로 7일/1달 기준 일간 변동금액과 총 평가금액을 계산합니다. 현금은 기간 내 고정 금액으로 반영됩니다.

대시보드의 `자산 스냅샷 저장` 버튼은 OpenAI를 호출하지 않습니다. yfinance의 `KRW=X` 환율과 현재 시장 데이터를 사용해 현재 포트폴리오 평가값을 `portfolio_snapshots`에 저장합니다. 대시보드 새로고침 시에도 가능한 경우 최신 USD-KRW 환율을 가져와 설정값에 반영합니다.

`비교` 탭의 AlphaPilot 운용 수익률은 추천 cycle의 기준가 대비 평균 추천 성과입니다. `내 실제 수익률`은 저장된 포트폴리오 스냅샷의 총 평가금액 기준 누적 수익률입니다. 미국 증시 대표선은 S&P 500을 사용합니다.

추가 매수 후보 목표 기간은 다음 기준으로 동작합니다.

```text
short  = 약 5거래일 목표
medium = 약 20거래일 목표
long   = 약 60거래일 목표
```

리포트의 `자산별 전략`은 요약 행을 먼저 보여주고, 행을 누르면 가격 구간과 1일/5일/20일 성과 추적 값이 펼쳐집니다. 보유 자산과 추가 후보는 같은 영역의 탭으로 전환합니다.

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

Post-MVP Phase 1~3 기능을 사용하려면 아래 파일도 순서대로 실행합니다.

```text
backend/app/db/migrations/005_create_report_jobs.sql
backend/app/db/migrations/006_create_portfolio_snapshots.sql
backend/app/db/migrations/007_create_recommendation_cycles.sql
```

이 세 마이그레이션은 각각 수동 리포트 생성 작업 상태, 포트폴리오 일별 스냅샷, 추천 생애주기 추적을 저장합니다. 모두 새 테이블을 추가하는 방식이라 기존 자산/리포트 데이터는 삭제하지 않습니다.

시장 데이터 일중 캐시 영속화(콜드스타트 후 외부 시세 재호출 폭주 방지)를 위해 아래 파일도 실행합니다.

```text
backend/app/db/migrations/008_create_market_data_cache.sql
```

이 마이그레이션도 새 테이블만 추가하며, 미적용 상태에서도 백엔드는 프로세스 내 캐시만으로 정상 동작합니다.

Phase 4(성과 분석/신뢰도 보정/노출 분석) 기능을 사용하려면 아래 파일도 실행합니다.

```text
backend/app/db/migrations/009_add_sector_columns.sql
backend/app/db/migrations/010_add_report_inputs.sql
```

009는 자산/후보 자산에 `sector` 컬럼(노출 분석용, 리포트 생성 시 자동 보충),
010은 리포트에 `report_inputs` JSONB(데이터 품질 스냅샷)를 추가합니다. 둘 다 additive이며,
010 미적용 상태에서도 리포트는 스냅샷 없이 정상 저장됩니다.

Phase 5(목표 배분/리밸런스/포지션 사이징/비용 차감 수익률) 기능을 사용하려면 아래 파일도 실행합니다.

```text
backend/app/db/migrations/011_add_allocation_and_cost_settings.sql
```

011은 `settings` 테이블에 목표 배분(국내/글로벌/현금 %), 종목별 비중 상한, 리밸런스 임계치,
1회 리스크 한도, 수수료/거래세/환전 스프레드 컬럼을 추가합니다 (additive, 기본값 포함).
**주의: 011 미적용 상태에서는 설정 저장(POST /api/settings)이 실패할 수 있으므로 함께 실행하세요.**

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

자동 리포트는 사용자가 사이트에 접속해 있어야 생성되는 방식이 아닙니다. GitHub Actions가 지정된 시간에 Render 백엔드를 직접 호출합니다. 자동 생성이 되지 않으면 GitHub 저장소의 `Actions` 탭에서 `Generate Domestic Market Report`, `Generate Global Market Report` 워크플로가 비활성화되어 있지 않은지, scheduled run이 생성되는지, `BACKEND_URL`과 `SCHEDULER_SECRET` secret이 현재 Render 값과 일치하는지 확인하세요.
스케줄러 API는 리포트 생성 작업을 즉시 `report_jobs`에 접수하고 202 응답을 반환합니다. 따라서 GitHub Actions의 성공은 "작업 접수 성공"을 의미하며, 실제 리포트 완료 여부는 앱의 `상태` 화면에서 최근 리포트 생성 job 상태로 확인합니다.

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

수동 생성은 비동기 방식입니다. 버튼을 누르면 백엔드가 즉시 작업 ID를 반환하고, 실제 시세 조회, 뉴스/동향 조회, OpenAI 호출, DB 저장은 Render 백엔드 안에서 계속 진행됩니다. 화면은 기존 리포트를 계속 보여주면서 작업 상태를 확인하고, 완료되면 최신 리포트 목록을 자동으로 갱신합니다.

작업 상태는 `report_jobs` 테이블에 저장됩니다. 각 단계별 소요 시간은 `상태` 화면의 최근 리포트 생성 단계에서 확인할 수 있습니다.
20분 이상 갱신되지 않은 `queued` 또는 `running` 작업은 중단된 작업으로 간주되어 자동 실패 처리되고, 새 리포트 생성을 다시 시작할 수 있습니다.

리포트가 저장되면 현재 포트폴리오 상태도 `portfolio_snapshots` 테이블에 함께 저장됩니다. 대시보드의 자산 변동 차트는 스냅샷이 2개 이상 있으면 스냅샷 기반으로 표시하고, 부족하면 기존처럼 최신 시세 이력 기반으로 표시합니다.

추천 전략은 `recommendation_cycles` 테이블에 생애주기로 저장됩니다. 같은 티커, 같은 목표 기간, 같은 액션이 이미 진행 중이면 새 cycle을 만들지 않고 기존 cycle을 유지합니다. 액션이 바뀌거나 목표가/손절가가 5% 이상 바뀌면 기존 cycle을 `superseded`로 닫고 새 cycle을 시작합니다.

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

## 성과 분석과 신뢰도 보정 (Phase 4)

- `성과 분석` 탭(`GET /api/recommendation-stats`)은 추천 cycle 실측 결과를
  액션×목표 기간×점수밴드(60 미만/60대/70대/80 이상)로 집계해
  목표 도달 승률, 평균 5일/20일 수익률, 평균 보유일, 표본 수를 보여줍니다.
- **신뢰도 보정**: 종료 표본이 30건 이상인 그룹은 리포트 생성 시
  `신뢰도 = 기술 점수 기반 신뢰도 × (0.5 + 실측 승률)` (계수는 0.6~1.3로 제한)로 보정됩니다.
  표본이 부족하면 기존 신뢰도를 유지하고 "보정 전(표본 부족)" 배지가 표시됩니다.
  전략 카드에는 신뢰도 산출 근거(기술 기여/과거 승률/뉴스 컨텍스트 반영 여부)가 함께 표시됩니다.
- **노출 분석**: 대시보드에 통화(KRW/USD)·시장(국내/미국/ETF/현금)·섹터별 비중이 표시되고,
  단일 종목 25% 또는 단일 섹터 40% 초과 시 집중도 경고가 나타납니다.
  섹터는 리포트 생성 시 yfinance 정보로 자동 보충되며, 필요하면 자산 API(`sector` 필드)로 직접 지정할 수 있습니다.
- **데이터 품질 배지**: 전략 카드에 시세 제공자, 최근 거래일, 데이터 지연 여부가 표시되고,
  리포트 생성 당시 입력 스냅샷이 `report_inputs`로 보존되어 사후 검증에 사용할 수 있습니다.
- 과거 성과 통계는 참고용이며 미래 수익을 보장하지 않습니다.

## 포트폴리오 의사결정 지원 (Phase 5)

자동 매매/주문 실행 없이 의사결정 지원 정보만 제공합니다.

- **ATR 기반 손절/목표가**: 변동성(ATR 14)이 정상 범위일 때
  `손절 = 현재가 − k×ATR`, `목표 = 현재가 + m×ATR`로 산정합니다
  (보수 1.5/2.5, 균형 2.0/3.0, 공격 2.5/4.0). ATR을 쓸 수 없으면 기존 고정 % 방식으로 폴백합니다.
- **목표 배분과 드리프트**: 설정에서 국내/글로벌/현금 목표 비중과 리밸런스 임계치(기본 5%p)를
  지정하면, 대시보드 `목표 대비 드리프트` 카드가 초과 항목에 "비중 축소/분할 매수 검토" 제안을
  표시하고 같은 정보가 리포트 LLM 컨텍스트에도 전달됩니다.
- **제안 투입 한도**: 신규 매수 후보(BUY/WATCH)에
  `min(가용 현금 × 성향별 비율, 1회 리스크 한도 ÷ 손절까지 거리)` 고정 리스크 방식의
  금액 한도를 표시합니다. 주문 수량/티켓은 제공하지 않습니다.
- **세후·비용 차감 수익률(추정)**: 설정의 수수료율/국내 거래세율/환전 스프레드를 반영해
  대시보드에 비용 차감 추정 수익률을 병기합니다. 단순 추정치이며 실제 세금/비용과 다를 수 있습니다.

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
- 성과 추적은 같은 티커와 같은 액션의 20일 평가가 끝나기 전에는 새 추적 로그를 다시 시작하지 않습니다. 액션이 바뀌거나 기존 20일 평가가 끝나면 새 추적이 시작될 수 있습니다.

## 검증 명령

```powershell
pytest backend/tests -v
ruff check .
black --check .
cd frontend
npm run lint
npm run format:check
npm test
npm run build
```

같은 검사가 `.github/workflows/ci.yml` 워크플로로 push/PR마다 자동 실행됩니다.

## 코드 구조 (2026-06 리팩토링)

- 백엔드 리포트 생성은 `backend/app/services/report/` 패키지로 분리되어 있습니다.
  `pipeline.py`(오케스트레이션), `candidate_screener.py`(후보 유니버스/스코어링),
  `prompt_builder.py`(LLM 프롬프트), `persistence.py`(저장), `tracking.py`(성과 백필).
  기존 `report_service.py` 경로는 하위 호환 re-export로 유지됩니다.
- 티커 정규화/시장 추론은 `backend/app/utils/tickers.py`, 한국어 라벨은
  `backend/app/utils/labels.py`로 단일화했습니다.
- 프론트엔드 공용 숫자 포맷은 `frontend/src/utils/formatters.js`, 공용 UI 문자열은
  `frontend/src/constants/strings.js`에 있습니다. 대시보드/리포트 화면은
  `components/dashboard/`, `components/reports/` 하위 컴포넌트로 분리되어 있습니다.
- 프론트엔드 도구: ESLint + Prettier + Vitest(+ React Testing Library), 차트는 Recharts를 사용합니다.
