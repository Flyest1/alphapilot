# AlphaPilot

AlphaPilot은 개인 자산을 등록하고, 국내/글로벌 시장 데이터와 기술 지표를 기반으로 AI 투자 전략 리포트를 생성하는 단일 사용자용 MVP입니다.

자동 매매와 주문 실행은 포함하지 않습니다. 브로커 API는 Toss Invest Open API의 조회 전용 계좌/보유주식 동기화만 지원합니다. 모든 리포트는 투자 의사결정 지원용이며 수익을 보장하지 않습니다.

## 구성

```text
Frontend: GitHub Pages + React + Vite + Tailwind CSS + GSAP
Backend: Oracle Cloud Always Free VM + FastAPI
Database: Supabase PostgreSQL
Scheduler: GitHub Actions
AI: OpenAI API
Market Data: pykrx, yfinance
News/Trend Context: GDELT DOC 2.0 API
Broker Sync: Toss Invest Open API (조회 전용)
```

## 사용 방법

1. GitHub Pages 주소에 접속합니다.
2. 첫 화면에 백엔드 서버 환경변수 `API_ACCESS_TOKEN` 값을 입력합니다.
3. `자산` 화면에서 보유 종목을 추가합니다. Toss Invest 환경변수를 설정한 경우 `Toss 보유주식 동기화`로 API 연동 자산을 가져올 수 있습니다.
4. `설정` 화면에서 AI 모델, 위험 성향, 추가 매수 후보 목표 기간, USD-KRW 환율을 조정합니다.
5. `설정` 화면에서 보유 외 추가 매수 후보군을 직접 추가하거나 비활성화합니다.
6. `상태` 화면에서 백엔드, Supabase, OpenAI 설정과 최근 리포트 상태를 확인합니다.
7. `리포트` 화면에서 국내/글로벌 리포트를 수동 생성하거나, GitHub Actions 정기 실행 결과를 확인합니다.
8. `AI 자문` 화면에서 8가지 수동 분석을 요청하고 작업 상태와 저장된 결과를 확인합니다.
9. `성과 추적`은 리포트 생성 이후 1일, 5일, 20일 가격 데이터가 쌓이면 표시됩니다.

AI 자문은 저평가 미국 주식, ETF 리밸런싱, 실적 발표 후 기회, AI 수혜 근거,
고배당 ETF 위험, SEC 공시 위험, ETF 중복, 6개월 섹터 전망을 제공합니다. 계산 가능한 값은
백엔드에서 계산하고 OpenAI는 저장된 근거 안에서만 설명합니다. 데이터가 없거나 오래된 경우
값을 추정하지 않고 `data-limited` 또는 `평가 불가`로 표시합니다. ETF 목표 비중과 관심 가격대는
검토용 정보이며 주문 수량·주문 미리보기·자동매매로 연결되지 않습니다.

`AI 자문` 화면은 저장소 마이그레이션과 OpenAI 설명 기능의 설정 상태를 별도로 표시합니다.
OpenAI 키가 없어도 결정론적 계산 결과는 제공하지만 AI 설명은 비활성 상태로 표시됩니다. ETF
비중을 모두 비우면 입력 ETF를 동일 비중으로 계산하고, 리밸런싱에서 ETF 자체를 입력하지 않으면
저장 자산의 평가금액 비중을 사용합니다.

Toss Invest로 동기화된 자산은 `Toss 연동` 배지와 동기화 시간이 표시됩니다. 기존에 같은 종목을 수동으로 입력해 둔 경우 동기화 결과에 중복 후보가 표시되며, 확인 후 수동 자산을 직접 삭제해 중복 계산을 피할 수 있습니다.

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

로컬 프론트엔드 포트를 바꿔 실행할 때는 백엔드 `FRONTEND_ORIGIN`에 해당 origin을 쉼표로 추가하세요.
예: `FRONTEND_ORIGIN=http://localhost:5173,http://127.0.0.1:5175`

## 백엔드 환경변수

Oracle VM, Render 롤백 환경, 또는 로컬 `backend/.env`에 설정합니다. 실제 키는 커밋하지 마세요.

```text
APP_ENV=development
FRONTEND_ORIGIN=http://localhost:5173,http://127.0.0.1:5173

SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_ANON_KEY=your-anon-key

OPENAI_API_KEY=your-openai-api-key
SCHEDULER_SECRET=change-this-secret
API_ACCESS_TOKEN=change-this-user-token
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TOSS_INVEST_CLIENT_ID=
TOSS_INVEST_CLIENT_SECRET=
TOSS_INVEST_ACCOUNT_ID=
FRED_API_KEY=
SEC_EDGAR_USER_AGENT=AlphaPilot <actual-contact-email>
SEC_EDGAR_CACHE_MAX_BYTES=1073741824

DOMESTIC_REPORT_TIME=08:30
GLOBAL_REPORT_TIME=22:30
AI_PROVIDER=openai
OPENAI_MODEL=gpt-5.6-luna
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

애플리케이션 기본값은 `settings` 테이블 값을 우선 사용하고, 값이 없으면 `.env`, 그 다음 Pydantic 기본값을 사용합니다.

## 프론트엔드 환경변수

GitHub Pages 빌드에는 API 주소만 필요합니다.

```text
VITE_API_BASE_URL=https://api.example.com
```

GitHub Pages는 HTTPS로 서비스되므로 운영 백엔드 URL도 HTTPS여야 합니다. Oracle VM의 공인 IP를
HTTP로만 연결하면 브라우저 mixed-content 정책 때문에 API 호출이 차단될 수 있습니다.

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

Phase 8(신호 품질 엔진)의 DB 기반 후보 유니버스를 사용하려면 아래 파일도 실행합니다.

```text
backend/app/db/migrations/012_create_candidate_universe.sql
```

012는 기존 하드코딩 후보군을 `candidate_universe` 테이블의 seed 데이터로 이전합니다. 기존
자산·리포트 데이터는 변경하지 않습니다.

Phase 9(알림 센터)를 사용하려면 아래 파일도 실행합니다.

```text
backend/app/db/migrations/013_create_notifications.sql
```

013은 `notifications` 테이블과 Telegram 이벤트별 opt-in 설정 컬럼을 추가합니다. 모두
additive이며 기존 데이터는 변경하지 않습니다.

Toss Invest 조회 전용 자산 연동을 사용하려면 아래 파일도 실행합니다.

```text
backend/app/db/migrations/014_add_asset_external_sync_fields.sql
```

014는 `assets` 테이블에 수동/외부 연동 출처, 외부 계좌/종목 키, 동기화 시간, 원본 payload
컬럼과 중복 방지 인덱스를 추가합니다. 기존 수동 자산은 `source='manual'` 기본값을 가지며,
삭제되거나 수정되지 않습니다.

추천 측정 무결성 개선을 적용하려면 008 적용 여부를 먼저 확인하고 신규 015를 실행합니다.

```text
backend/app/db/migrations/008_create_market_data_cache.sql
backend/app/db/migrations/015_improve_recommendation_cycle_measurement.sql
```

015는 추천 사이클에 실제 장벽 도달 시각, 원시 기술점수, 보정 전 신뢰도, 최종 보정 신뢰도
컬럼을 additive 방식으로 추가합니다. 2026-07 점검 당시 운영 Supabase에는 008 테이블이 없어
SQL Editor에서 008과 015를 순서대로 수동 적용해야 합니다.

신호 모델 그림자 평가 기반을 사용하려면 아래 파일도 실행합니다.

```text
backend/app/db/migrations/016_create_signal_model_evaluations.sql
```

현재 운영 Supabase에는 2026-07-17에 016을 수동 적용했습니다. 새 Supabase 환경을 구성하거나
데이터베이스를 복원한 경우에는 동일한 마이그레이션을 별도로 실행해야 합니다.
적용 직후 운영 저장소 조회 결과는 `available / not_configured`, champion `technical_score/v1`,
challenger와 활성 평가 없음, 정기·수동 표본 각각 0건으로 확인했습니다.

016은 현재 운영 기술점수 모델을 변경하지 않고, 불변 모델 버전과 역할 배정 이력, 12주 평가
원장, 모델별 관측값, 리포트 입력 연결을 별도 테이블에 저장합니다. 기존 리포트와 추천 사이클
테이블은 변경하지 않습니다. 마이그레이션은 현재 모델을 champion으로 한 번 등록하지만
challenger나 평가 실행은 만들지 않습니다. 따라서 적용 직후 성과 분석 화면에는 `평가 미설정`과
`운영 미반영` 상태가 정상적으로 표시됩니다.

정기 스케줄 리포트만 공식 그림자 표본으로 표시하고, 수동 리포트는 동일 입력을 재현하기 위한
연결만 저장합니다. 마이그레이션이 아직 적용되지 않아도 기존 리포트 생성은 계속되며 그림자
평가 API는 `migration_required` 상태를 반환합니다.

AI 자문 작업 상태와 결과 이력을 저장하려면 아래 파일도 실행합니다.

```text
backend/app/db/migrations/017_create_advisory_analyses.sql
```

017은 `advisory_jobs`, `advisory_analyses` 테이블과 활성 중복 요청 방지 인덱스를 additive 방식으로
추가합니다. 적용 전에도 기존 리포트·자산 기능은 유지되지만, Supabase를 사용하는 운영 환경에서
AI 자문 요청을 저장하려면 반드시 적용해야 합니다. 적용 전 `GET /api/advisory/status`는
`migration_required`를 반환하고 자문 화면에 실행할 SQL 파일을 안내합니다.

2026-07 AI 모델 기본값과 미국 후보 유니버스 확대를 기존 데이터베이스에 반영하려면 아래 파일을
순서대로 실행합니다.

```text
backend/app/db/migrations/018_upgrade_default_openai_model.sql
backend/app/db/migrations/019_expand_us_candidate_universe.sql
```

018은 기존 기본 모델 값이 `gpt-5.4-mini`인 설정만 `gpt-5.6-luna`로 변경하고 SQL 기본값도
동기화합니다. 배포 시에도 기존 기본값만 동일하게 1회 승격하므로 즉시 수동 실행이
어려운 경우 새 모델이 먼저 적용됩니다. 019는 기존 미국 주식 15개를 유지하면서 기술, 헬스케어, 에너지, 소비재 등
15개 종목을 추가해 기본 미국 주식 유니버스를 30개로 확장합니다.

AI 자문의 SEC 공시 분석은 무료 공식 EDGAR 데이터를 읽기 전용으로 사용합니다.
`SEC_EDGAR_USER_AGENT`에는 애플리케이션 이름과 실제 연락 가능한 이메일을 입력해야 하며,
공식 JSON/XML·complete-submission 문서·N-PORT 자료만 조회합니다. N-PORT 결과는 공시 지연이
있는 자료이며 현재 또는 일일 ETF 수급으로 표시하지 않습니다.

금리와 인플레이션 등 거시 입력은 `FRED_API_KEY`가 설정된 경우 무료 FRED API에서 조회합니다.
FRED 자료는 관측값이며 미래 전망이나 수익을 보장하지 않습니다.

> This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.

Supabase service role key는 RLS를 우회합니다. 반드시 백엔드 서버 환경변수에만 보관하고, 프론트엔드나 에러 메시지에 노출하지 마세요.

## Oracle Cloud Always Free 백엔드 배포

백엔드는 Oracle Cloud Always Free VM으로 이전할 수 있습니다. Supabase는 그대로 사용하며,
Oracle은 FastAPI 서버만 대체합니다.

전제 조건:

- Oracle Cloud Always Free VM, 권장 OS는 Ubuntu 22.04 LTS입니다.
- VM 보안 목록 또는 네트워크 보안 그룹에서 `80`, `443`, SSH 포트를 허용합니다.
- GitHub Pages에서 호출하려면 `https://api.example.com` 같은 HTTPS 도메인이 필요합니다.
  도메인의 A 레코드는 Oracle VM 공인 IP를 가리켜야 합니다.

VM 최초 준비:

```bash
sudo apt update
sudo apt install -y git build-essential python3.10 python3.10-dev python3.10-venv nginx certbot python3-certbot-nginx
sudo git clone https://github.com/flyest1/alphapilot.git /opt/alphapilot
cd /opt/alphapilot
sudo mkdir -p /etc/alphapilot
sudo cp deploy/oracle/backend.env.example /etc/alphapilot/backend.env
sudo chmod 600 /etc/alphapilot/backend.env
sudo nano /etc/alphapilot/backend.env
sudo bash deploy/oracle/install_backend.sh /opt/alphapilot api.example.com
```

`/etc/alphapilot/backend.env`에 최소 아래 값을 실제 값으로 채웁니다.

```text
APP_ENV=production
FRONTEND_ORIGIN=https://flyest1.github.io
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
SUPABASE_ANON_KEY
OPENAI_API_KEY
SCHEDULER_SECRET
API_ACCESS_TOKEN
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
TOSS_INVEST_CLIENT_ID
TOSS_INVEST_CLIENT_SECRET
TOSS_INVEST_ACCOUNT_ID
FRED_API_KEY
SEC_EDGAR_USER_AGENT
```

설치 후 환경변수를 다시 수정했다면 백엔드를 재시작합니다.

```bash
sudo systemctl restart alphapilot-backend
curl http://127.0.0.1:8000/health
```

nginx가 80 포트로 정상 응답하면 HTTPS 인증서를 발급합니다.

```bash
sudo certbot --nginx -d api.example.com
curl https://api.example.com/health
```

이후 GitHub repository secrets를 새 Oracle 백엔드 주소로 바꿉니다.

```text
VITE_API_BASE_URL=https://api.example.com
BACKEND_URL=https://api.example.com
SCHEDULER_SECRET=/etc/alphapilot/backend.env에 설정한 SCHEDULER_SECRET과 같은 값
```

백엔드 코드를 갱신하려면 Oracle VM에서 아래 명령을 실행합니다.

```bash
sudo bash /opt/alphapilot/deploy/oracle/deploy_backend.sh /opt/alphapilot
```

또는 GitHub repository secrets에 `ORACLE_SSH_HOST`, `ORACLE_SSH_USER`,
`ORACLE_SSH_PRIVATE_KEY`를 설정한 뒤 `Deploy Backend to Oracle VM` 워크플로를 수동 실행할 수 있습니다.
이 방식은 VM 사용자에게 `/opt/alphapilot/deploy/oracle/deploy_backend.sh`를 passwordless sudo로
실행할 권한이 있어야 합니다.

Oracle VM 운영 시 OS 보안 업데이트, systemd 프로세스 상태, nginx 설정, TLS 인증서 갱신은 직접 관리해야 합니다.

Toss Invest 연동을 쓰지 않으면 `TOSS_INVEST_*` 값은 비워둘 수 있습니다. 연동을 쓰는 경우
client id, client secret, 조회할 계좌 식별값을 백엔드 서버 환경변수에만 저장하세요. 프론트엔드
환경변수, GitHub Pages secret, Supabase 테이블에는 저장하지 않습니다.

## Render 롤백

`backend/render.yaml`은 롤백용으로 유지합니다. Oracle VM에 문제가 생기면 기존 Render 서비스의
환경변수를 동일하게 맞춘 뒤 GitHub repository secrets의 `VITE_API_BASE_URL`과 `BACKEND_URL`을
Render URL로 되돌리면 됩니다. Render Free는 유휴 상태 후 cold start가 발생할 수 있습니다.

## GitHub Pages 배포

GitHub repository secrets에 아래 값을 설정합니다.

```text
VITE_API_BASE_URL=https://api.example.com
```

`VITE_API_ACCESS_TOKEN`은 더 이상 사용하지 않습니다. 기존에 등록되어 있어도 코드에서 읽지 않으며, 삭제해도 됩니다.

## GitHub Actions 스케줄러

GitHub repository secrets에 아래 값을 설정합니다.

```text
BACKEND_URL=https://api.example.com
SCHEDULER_SECRET=백엔드 서버에 설정한 SCHEDULER_SECRET과 같은 값
```

자동 리포트는 사용자가 사이트에 접속해 있어야 생성되는 방식이 아닙니다. GitHub Actions가 지정된 시간에 백엔드를 직접 호출합니다. 자동 생성이 되지 않으면 GitHub 저장소의 `Actions` 탭에서 `Generate Domestic Market Report`, `Generate Global Market Report` 워크플로가 비활성화되어 있지 않은지, scheduled run이 생성되는지, `BACKEND_URL`과 `SCHEDULER_SECRET` secret이 현재 백엔드 값과 일치하는지 확인하세요.
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

수동 생성은 비동기 방식입니다. 버튼을 누르면 백엔드가 즉시 작업 ID를 반환하고, 실제 시세 조회, 뉴스/동향 조회, OpenAI 호출, DB 저장은 백엔드 서버 안에서 계속 진행됩니다. 화면은 기존 리포트를 계속 보여주면서 작업 상태를 확인하고, 완료되면 최신 리포트 목록을 자동으로 갱신합니다.

작업 상태는 `report_jobs` 테이블에 저장됩니다. 각 단계별 소요 시간은 `상태` 화면의 최근 리포트 생성 단계에서 확인할 수 있습니다.
20분 이상 갱신되지 않은 `queued` 또는 `running` 작업은 중단된 작업으로 간주되어 자동 실패 처리되고, 새 리포트 생성을 다시 시작할 수 있습니다.

리포트가 저장되면 현재 포트폴리오 상태도 `portfolio_snapshots` 테이블에 함께 저장됩니다. 대시보드의 자산 변동 차트는 스냅샷이 2개 이상 있으면 스냅샷 기반으로 표시하고, 부족하면 기존처럼 최신 시세 이력 기반으로 표시합니다.

추천 전략은 `recommendation_cycles` 테이블에 생애주기로 저장됩니다. 같은 티커, 같은 목표 기간, 같은 액션이 이미 진행 중이면 새 cycle을 만들지 않고 기존 cycle을 유지합니다. 액션이 바뀌거나 목표가/손절가가 5% 이상 바뀌면 기존 cycle을 `superseded`로 닫고 새 cycle을 시작합니다.

리포트 화면은 초기 진입 속도를 위해 리포트 본문, 전략, 자산, 설정만 먼저 불러옵니다. 추천 생애주기와 기존 성과 로그는 `성과 데이터 연결` 또는 `추천 생애주기와 성과 로그 보기`를 눌렀을 때만 조회합니다. 20일 수익률순 정렬을 선택해도 같은 성과 데이터 연결이 먼저 실행됩니다.

보유 외 추가 매수 후보는 `설정` 화면의 후보군 목록을 우선 사용합니다. 직접 등록한 활성 후보가 없으면 앱에 포함된 기본 후보군을 사용합니다.

## 뉴스/동향 반영

리포트 생성 시 GDELT DOC 2.0 API에서 최근 3일 뉴스/동향 헤드라인을 조회해 AI 분석 컨텍스트로 전달합니다. 별도 뉴스 섹션을 화면에 만들지는 않고, 관련성이 있을 때만 시장 요약, 위험 요인, 기회 요인, 종목별 판단 근거에 반영합니다. 전체 6회 쿼리 중 시장 공통 주제 3회와 종목 3회를 예약하고, 종목 예산은 보유 종목 2개와 우선 후보 1개를 먼저 배정합니다. 남는 예산만 다음 우선순위로 넘깁니다.

GDELT는 무료/무키 기반의 글로벌 뉴스 검색 API입니다. 제공자 장애, 검색 누락, 언어/출처 편향, 호출량 제한(HTTP 429)이 있을 수 있으며, 뉴스 조회 실패가 리포트 생성을 막지는 않습니다. Oracle 운영 측정에서 TLS handshake가 약 8~10초 걸리고 5초 이내 반복 요청에 429가 발생해, 연결 15초·읽기 10초 제한과 쿼리 간 5.5초 간격을 사용합니다. 앱은 GDELT 쿼리를 순차 실행하며 일시적 DNS·TLS·timeout·network·HTTP 오류만 5초 이상 대기 후 한 번 재시도합니다. 일부 쿼리만 실패하면 `partial`, 전부 실패하면 `unavailable`로 기록하고 기술·시장 데이터 중심으로 계속 생성합니다.

동일 URL의 추적 파라미터, 유사 제목과 동일 이벤트를 제거하고, 수집 시각 기준 3일을 벗어나거나 시각이 없고 종목명이 헤드라인과 일치하지 않는 기사는 제외합니다. 기사 본문은 읽지 않으므로 모든 근거는 `headline-only`입니다. `report_inputs.news_context`에는 검색어와 범위, 종목, 제목, 도메인, URL, 기사 시각, 수집 시각, 실패 분류, 증거 ID와 실제 리포트 인용 경로를 저장합니다. 제외된 기사도 중복 URL, 유사 이벤트, 시각 오류, 관련성 부족, 컨텍스트 한도 등의 사유와 함께 보존합니다. 뉴스는 현재 신뢰도 숫자를 직접 변경하지 않으므로 `news_contribution_mode=not_modeled`, `news_contribution_score=0`으로 기록합니다.

Oracle VM에서 뉴스가 계속 `unavailable`이면 서비스 실행 사용자 기준으로 아래를 확인합니다.

```bash
python -c "import socket; print(socket.getaddrinfo('api.gdeltproject.org', 443))"
openssl s_client -connect api.gdeltproject.org:443 -servername api.gdeltproject.org </dev/null
curl -sS -o /dev/null -w 'connect=%{time_connect} tls=%{time_appconnect} start=%{time_starttransfer} total=%{time_total}\n' 'https://api.gdeltproject.org/api/v2/doc/doc?query=NASDAQ&mode=artlist&format=json&maxrecords=1&timespan=3d'
sudo journalctl -u alphapilot-backend --since '30 minutes ago'
```

DNS, 인증서 체인/SNI, outbound 443 방화벽, CA bundle, 응답 시작 시간을 순서대로 확인합니다. GitHub Actions 사전 수집은 현재 구현하지 않으며, Oracle에서 반복 실패가 확인된 경우에만 별도 캐시 테이블과 스케줄러 계약을 설계합니다.

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
- **검토용 투입 금액 상한(모델 추정)**: 신규 매수 후보(BUY/WATCH)는 하나의 현금 예산과
  포트폴리오 손실 예산을 공유합니다. 손절 거리뿐 아니라 변동성·갭 위험, 단일 자산/시장/통화/
  섹터 집중도, 평균 거래대금, 베타와 보유 자산 상관 노출을 함께 계산하고, 사용 가능한 제약 중
  가장 보수적인 금액과 실제 적용된 제약을 표시합니다. 금액들은 동시에 모두 사용할 수 있는
  주문 예산이 아니며, 실제 손실 한도나 체결을 보장하지 않습니다. 주문 수량/티켓은 제공하지 않습니다.
- **과거 검증 기반 시나리오 기대값**: 동일 액션·목표 기간·원시 기술점수 구간의 운영 종료
  표본이 30건 이상일 때만 목표 도달/손절 도달/기타 종료 빈도와 목표·하방 폭, 추정 거래비용을
  분리해 기대값을 표시합니다. 신호 점수를 확률로 사용하지 않으며, 표본 또는 데이터 품질이
  부족하면 숫자를 만들지 않고 `기대값 미산출`로 안내합니다.
- **계산 감사 기록**: `report_inputs.portfolio_risk`에 모델 버전, 후보 처리 순서와 제외 사유,
  포트폴리오 손실·통화별 현금 예산, 환율·비용·집중도 설정을 저장합니다. 상관·베타는 현재
  리포트 시장에 한정하지 않고 시세를 확보한 전체 보유 자산을 사용합니다.
- **세후·비용 차감 수익률(추정)**: 설정의 수수료율/국내 거래세율/환전 스프레드를 반영해
  대시보드에 비용 차감 추정 수익률을 병기합니다. 단순 추정치이며 실제 세금/비용과 다를 수 있습니다.

## 사용자 편의 기능 (Phase 6)

- **오늘 확인할 것**: 대시보드 최상단 브리핑 카드 — 최근 7일 목표/손절 도달 종목,
  보유 자산의 축소·매도 판단(조건 체크), 리밸런스·집중도 경고, 신규 매수 후보(신뢰도순),
  데이터 지연 종목을 한 줄씩 요약합니다.
- **직전 리포트 대비 변화**: 리포트 화면에서 같은 타입의 직전 리포트와 비교해
  액션 변경(예: 보유→축소), 신뢰도 변화(±10 이상), 신규/제외 종목을 강조합니다.
- **전략 정렬**: 자산별 전략을 신뢰도순 또는 20일 수익률순으로 정렬할 수 있습니다.
  카드형 아코디언 UI라 모바일에서도 동일하게 동작합니다.
- **PWA 설치**: manifest와 서비스워커가 포함되어 홈 화면에 설치할 수 있습니다.
  서비스워커는 정적 자산(앱 셸)만 캐시하고, API 응답은 토큰 보호를 위해 SW 캐시에 저장하지
  않습니다. 마지막 리포트의 오프라인 열람은 기존 localStorage API 캐시가 담당합니다.
- **CSV 가져오기/내보내기**: 자산 화면에서 보유 자산을 CSV로 백업하거나 일괄 등록할 수 있습니다.
  헤더는 영문(market,ticker,name,quantity,avg_price,currency,sector,memo)과
  한글(시장/종목코드/종목명/수량/평균단가/통화/섹터/메모)을 모두 지원하며,
  잘못된 행은 건너뛰고 행 번호와 함께 사유를 보여줍니다.
- **대시보드 차트 Recharts 전환**: 일별 자산 변동 차트가 막대(일간 변동)+선(총 평가금액)
  복합 차트로 바뀌어 툴팁과 반응형을 지원합니다.

## 신호 품질 엔진 (Phase 8)

- **DB 후보 유니버스**: 리포트 후보 스크리너는 `candidate_universe` 테이블을 사용합니다.
  사용자가 직접 등록한 활성 후보가 있으면 기존처럼 해당 후보를 우선합니다.
- **주간 후보 갱신**: `Refresh Candidate Universe` GitHub Actions가 매주 일요일 21:00 UTC에
  `POST /api/candidate-universe/refresh`를 호출합니다. pykrx 시가총액 상위 종목, 승인된
  yfinance 기반 미국 주식 30개와 주요 ETF 정보를 갱신하며, `BACKEND_URL`과
  `SCHEDULER_SECRET`을 사용합니다.
- **규칙 백테스트**: 성과 분석 화면에서 국내/글로벌 점수 규칙 시뮬레이션을 수동 실행할 수
  있습니다. 운영과 동일한 투자성향·호라이즌·ATR 목표/손절 규칙을 사용하고 수수료, 국내
  거래세, 환전 스프레드, 거래대금 기반 보수적 슬리피지를 추정 반영합니다. 비용 전후 누적성과,
  Sharpe/Sortino/Calmar, 최대낙폭, 기대값, profit factor, 단순 보유·SMA·모멘텀 기준선,
  시장 국면별 결과와 purge/embargo를 적용한 워크포워드 fold를 함께 표시합니다.
  현재 후보 유니버스를 과거에도 그대로 사용하므로 생존편향 가능성이 있으며, 실제 체결이나
  미래 수익을 보장하지 않습니다. 누적·연환산 성과는 겹치지 않는 평가 코호트를 날짜별
  동일가중한 방향 정규화 신호 바스켓이며 실제 포트폴리오 수익률이 아닙니다. 최소 30개
  평가 코호트, 3개 워크포워드 fold, 시장별 20개 표본을 충족하지 않으면 연구 표본 부족으로
  간주하며 운영 규칙을 자동으로 변경하지 않습니다.
- **직교 신호 연구 진단**: 백테스트 응답과 성과 분석 화면에서 추세·모멘텀·거래량·유동성·
  변동성·낙폭·시장 상대강도 후보의 중복도, 분위별 비용 차감 수익 차이, 기존 기술점수 대비
  증분 기대값과 워크포워드 일관성을 확인할 수 있습니다. 이 진단은 항상 연구 전용이며
  운영 기술점수, 추천 액션, 리포트 생성 규칙을 자동으로 변경하지 않습니다.
- **그림자 평가 기반**: `GET /api/signal-models/evaluation`과 성과 분석 화면에서 champion,
  challenger, 12주 평가 상태와 정기/수동 입력 연결 수를 읽기 전용으로 확인합니다. 현재는
  champion 입력 원장만 수집하며 challenger 규칙과 승격 임계값은 아직 설정하지 않았습니다.
  자동 승격 API, 스케줄러, 버튼은 없고 모든 결과는 `연구 전용`, `운영 미반영`, `수동 승격만`
  원칙을 유지합니다.
- **배당·실적 일정**: yfinance가 제공하는 향후 60일 보유 자산 일정을 리포트 위험·기회와
  대시보드에 표시합니다. 공급자 데이터가 없거나 지연되면 일정이 표시되지 않을 수 있습니다.

## 추천 측정 무결성 (2026-07 Phase 0)

- BUY/HOLD/WATCH는 상승 방향, SELL/REDUCE는 하락 방향으로 목표·손절 장벽을 판정합니다.
- 같은 거래일에 목표와 손절을 모두 통과하면 보수적으로 `ambiguous`로 종료하고 실제 거래일을
  `barrier_hit_at`에 저장합니다.
- 추천 통계의 점수 구간은 최종 confidence가 아니라 원시 `technical_score`를 사용합니다.
- 운영 전략과 규칙 백테스트는 `StrategyService`의 동일한 투자성향별 액션 및 ATR 목표·손절
  규칙을 사용합니다.
- 정상 기술점수는 SMA120 계산이 가능한 최소 120 거래일을 요구합니다. 부족하면 WATCH,
  confidence 0, `data-limited`로 처리합니다.

기존 추천 사이클은 migration 015 적용 후 먼저 미리보기하고, 실제 적용 시 JSON 백업을 생성해
재산출합니다.

```powershell
python scripts/recalculate_recommendation_cycles.py
python scripts/recalculate_recommendation_cycles.py --apply
```

운영 Supabase에는 2026-07-15 migration 008과 015를 적용하고 기존 사이클을 재산출했습니다.
재산출 과정에서 구형 SELL/REDUCE 사이클 53건의 목표·손절 위치를 방향 규칙에 맞게 교환했고,
목표와 손절이 모두 기준가 아래에 있던 비정상 사이클 9건은 `measurement_excluded`로 격리해
추천 통계와 confidence 보정 표본에서 제외했습니다. 미리보기와 적용 결과는 gitignored
`backups/recommendation_cycles_recalculation_*.json`에 기록되며, 실제 적용 전에 전체 JSON
백업을 생성합니다. 적용 중 오류나 사후 검증 실패가 발생하면 백업값으로 변경 행을 복원하고
0이 아닌 종료 코드로 실패합니다. 동일 상태에서 재실행하면 변경 건수는 0이어야 합니다.

재산출 전 기존 승률은 전략의 실제 성공률 근거로 사용하지 않습니다.

## AI 정량 사실 보호 (2026-07 Phase 4)

- `ReportContent`의 `confidence_detail`과 `position_sizing`은 기존 UI 기능을 유지하기 위한
  공식 선택 필드입니다.
- OpenAI는 요약, 위험·기회, 종목 근거와 무효화 조건 같은 설명만 작성합니다. 리포트 유형,
  생성 시각, 지수 데이터, 포트폴리오 평가액·수익률, 종목 목록, 현재가, 액션, confidence,
  매수·매도 범위, ATR 목표가·손절가와 포지션 크기는 백엔드 값으로 다시 확정합니다.
- 입력에 없는 종목과 정규화 중복 종목은 제거하고, 누락된 종목은 백엔드 전략으로 복원합니다.
  stale/data-limited 종목은 WATCH, confidence 0과 백엔드 설명을 유지합니다.
- 수익 보장, 무위험, 반드시 매수·매도 같은 금지 표현이 발견되면 AI 설명을 폐기하고
  technical-only fallback을 저장합니다. fallback confidence는 최종 보정 후에도 60을 넘지 않습니다.
- `report_inputs.ai_generation`에 `ai_narrative`/`technical_only` 모드, 모델, 시도 횟수,
  fallback 사유와 백엔드가 복원한 필드 경로를 저장합니다. 상태 화면에서도 최신 모드를 확인할
  수 있습니다.
- 2026-07-15 Oracle 운영 환경에서 국내·글로벌 리포트를 각각 생성해 `ai_narrative`,
  `gpt-5.4-mini`, 1회 성공과 백엔드 사실 복원 진단이 저장되는 것을 확인했습니다.

## 알림 센터 (Phase 9)

- **인앱 알림**: 스케줄 리포트가 완료되면 리포트 완료, 목표/손절 도달, 추천 cycle 종료,
  리밸런스 드리프트 경고를 `notifications`에 저장합니다. 알림 화면에서 개별 또는 전체 읽음
  처리를 할 수 있습니다.
- **수동 리포트 제외**: 사용자가 화면에서 생성한 수동 리포트는 알림을 만들지 않습니다.
- **Telegram 선택 전송**: 백엔드 서버 환경변수 `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID`를 설정하고 설정 화면에서 이벤트별 전송을 켜면 동일 이벤트를 Telegram
  Bot API로 보냅니다. 환경변수가 없거나 전송에 실패해도 인앱 알림과 리포트 생성은 계속됩니다.
- **보안**: Telegram token과 Chat ID는 프론트엔드 번들/API 응답에 포함되지 않습니다.

## Toss Invest 조회 전용 연동

- **목적**: Toss Invest Open API에서 계좌 목록과 보유주식만 조회해 AlphaPilot의 `assets`에
  `Toss 연동` 자산으로 저장합니다. 수동 자산은 계속 별도로 관리할 수 있습니다.
- **API**: `GET /api/toss/status`는 백엔드 환경변수 설정 여부만 반환하고,
  `POST /api/toss/sync`는 `/oauth2/token`, `/api/v1/accounts`, `/api/v1/holdings`만 호출합니다.
- **중복 처리**: 같은 시장/티커의 수동 자산이 있으면 동기화 결과에 중복 후보로 표시합니다.
  자동 삭제하지 않으므로 사용자가 확인 후 수동 자산을 삭제해야 합니다.
- **보안**: `TOSS_INVEST_CLIENT_ID`, `TOSS_INVEST_CLIENT_SECRET`,
  `TOSS_INVEST_ACCOUNT_ID`는 백엔드 서버 또는 로컬 `backend/.env`에만 저장합니다. 프론트엔드,
  localStorage, Supabase, GitHub Pages 빌드에는 넣지 않습니다.
- **금지 범위**: 주문 생성/정정/취소, 주문 내역, 매수 가능금액, 매도 가능수량, 주문 미리보기,
  자동 리밸런스, 자동 매매는 구현하지 않습니다.

## Phase 10 설계 상태

멀티유저/상업화는 구현하지 않았습니다. 목표 인증/RLS 구조, 기존 데이터 이관, 사용자별 비용
통제, 스케줄 worker 선택, 법률 검토 게이트는
`docs/phase10_multi_user_design.md`에 설계만 정리되어 있습니다. 명시적 승인과
`AGENTS.md` 대개정 전에는 Supabase Auth, `user_id`, RLS, 결제 기능을 추가하지 않습니다.

## 보안 범위

이 MVP는 단일 사용자용입니다. Supabase Auth, 로그인/회원가입, 사용자별 권한 분리는 구현하지 않았습니다.

현재 보안 방식은 다음과 같습니다.

- 모든 `/api/*` 요청은 토큰이 필요합니다.
- 정기 리포트 생성 엔드포인트는 `SCHEDULER_SECRET`을 사용합니다.
- 일반 API와 수동 리포트 생성은 `API_ACCESS_TOKEN`을 사용합니다.
- 두 값은 반드시 서로 다르게 설정하세요. 같게 설정하면 스케줄러 시크릿으로 일반 API까지 호출할 수 있습니다.
- GitHub Pages 정적 URL 자체는 public일 수 있지만, 토큰 없이는 백엔드 데이터 API를 호출할 수 없습니다.
- Toss Invest credential은 백엔드 환경변수에만 두며 API 응답에는 credential 값을 반환하지 않습니다.

주의: `API_ACCESS_TOKEN`이 유출되면 해당 토큰을 가진 사람이 자산과 리포트 데이터에 접근할 수 있습니다. 이 방식은 production-grade 인증이 아니라 단일 사용자 MVP용 접근 게이트입니다.

## 제한 사항

- 자동 매매와 주문 실행 없음
- Toss Invest 연동은 조회 전용 보유주식 동기화만 지원
- 수익 보장 없음
- 뉴스/동향 컨텍스트는 GDELT DOC 2.0 API에 한정되며 누락되거나 호출량 제한을 받을 수 있음
- pykrx/yfinance 데이터는 지연되거나 실패할 수 있음
- Oracle VM 운영, 보안 업데이트, TLS 인증서 갱신은 직접 관리해야 함
- Render 롤백 시 Render Free cold start 가능
- GitHub Actions 예약 실행 지연 가능
- 글로벌 리포트 cron은 미국 서머타임 자동 보정 없음
- 추가 매수 후보군은 직접 등록한 후보군 또는 미국 주식 30개를 포함한 기본 후보군을 사용하며,
  별도 유료 스크리닝 API를 사용하지 않음
- 성과 추적은 같은 티커와 같은 액션의 20일 평가가 끝나기 전에는 새 추적 로그를 다시 시작하지 않습니다. 액션이 바뀌거나 기존 20일 평가가 끝나면 새 추적이 시작될 수 있습니다.
- migration 015 적용과 기존 사이클 재산출 전 추천 승률은 방향성 오류가 포함될 수 있어 의사결정 근거로 사용하지 않음

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
- 프론트엔드 도구: ESLint + Prettier + Vitest(+ React Testing Library), Tailwind CSS,
  GSAP, Recharts를 사용합니다.

## SEC EDGAR·FRED 운영 설정 (2026-07)

SEC EDGAR와 FRED는 사용자 승인된 읽기 전용 데이터 소스이며, AI 자문 기능의 기본 코드 연결과 운영 배포가 완료되었습니다. SEC 공시 분석과 FRED 기반 거시 입력은 설정과 원천 데이터가 모두 준비된 경우에만 사용합니다. 데이터가 없거나 오래되었거나 형식이 올바르지 않으면 값을 추정하지 않고 `data-limited`, `insufficient_data` 또는 사용할 수 없는 결과로 표시합니다.

2026-07-17 운영 검증에서는 8가지 자문 유형의 인증 요청, 비동기 polling, Supabase 작업·분석 이력 저장을 모두 확인했습니다. 저평가·실적 발표 후 기회는 가격 조건과 펀더멘털 개선 조건을 동시에 만족하지 않으면 후보에서 제외하며, ETF 보유종목이 없으면 중복률·분산도를 0으로 단정하지 않습니다. AAPL SEC 검증에서는 최신 10-K, 10-Q, 8-K 공식 문서와 근거 추적을 확인했습니다.

Oracle VM에서 실제 운영 값을 설정하는 절차는 다음과 같습니다. 아래 예시의 자리표시자에는 실제 값을 **서버에서만** 입력합니다. API 키와 실제 연락 이메일은 채팅, Git 저장소, 커밋, 이슈, 프론트엔드 번들, GitHub Pages, Supabase 또는 로그에 노출하지 마세요.

```bash
sudo nano /etc/alphapilot/backend.env
```

```env
# 실제 FRED API 키를 서버에서만 입력합니다. 저장소에는 넣지 않습니다.
FRED_API_KEY=<actual-fred-api-key>

# SEC 요청 식별용: 실제 연락 가능한 이메일을 서버에서만 입력합니다.
SEC_EDGAR_USER_AGENT=AlphaPilot <actual-contact-email>
```

파일을 저장한 뒤 권한과 서비스 상태를 확인하고 백엔드를 재시작합니다.

```bash
sudo chmod 600 /etc/alphapilot/backend.env
sudo systemctl restart alphapilot-backend
sudo systemctl status alphapilot-backend --no-pager
curl http://127.0.0.1:8000/health
```

- SEC EDGAR는 공식 `data.sec.gov`, 승인된 `www.sec.gov` 티커 매핑, 공식 Archives 공시 자료만 읽기 전용으로 사용합니다. 요청은 `SEC_EDGAR_USER_AGENT`를 선언하고 애플리케이션 전체에서 초당 5회 이하로 제한합니다. 공시 위험 분석의 기본 조회 기간은 최근 365일이며 사용자가 1~365일 범위로 줄일 수 있습니다. complete-submission 응답은 최대 16MB, 정규화 텍스트는 최대 750,000자로 제한합니다.
- FRED 관측값은 과거 증거이며 미래 전망이나 투자 수익을 보장하지 않습니다. FRED 기반 화면에는 다음 고지를 표시합니다: “This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.”
- SEC N-PORT 보유·흐름 자료에는 공시 기준 기간과 공시 지연을 함께 표시합니다. 현재 또는 일별 ETF 자금 흐름으로 제시하지 않습니다.
- yfinance 가격·거래량 및 ETF 메타데이터는 제공 범위와 갱신 시점에 제한이 있는 프록시입니다. 이를 실시간 ETF 자금 흐름, 완전한 ETF 구성 내역 또는 확정적 시장 신호로 해석하지 않습니다.
- 현재 ETF 구성 분석은 공급자가 제공하는 상위 10개 보유종목 범위입니다.

AI 자문 Bundle B·C는 다음 안정화와 화면 개선을 포함합니다.

- SEC complete-submission 원문은 `backend/.cache/sec-edgar`에 accession별로 영속 캐시합니다. CIK·accession·공식 URL·SHA-256·바이트 길이를 검증하고 원자적으로 저장하며, 손상된 파일은 사용하지 않습니다.
- 캐시는 최대 256개 accession과 기본 1GB 바이트 상한을 함께 적용하고 최근 사용 시각을 기준으로
  오래된 완전한 파일 쌍을 제거합니다. 바이트 상한은 서버 전용
  `SEC_EDGAR_CACHE_MAX_BYTES`로 조정할 수 있으며 상태 화면에서 사용량을 확인할 수 있습니다.
- 실행 중인 자문 작업은 약 15초마다 `updated_at` heartbeat를 기록합니다. Oracle의 단일 Uvicorn 프로세스가 재시작되면 저장된 `queued`·`running` 작업을 다시 확인하고, 이미 분석이 저장된 작업은 완료 상태로 정합화하며 나머지는 한 번 재실행합니다.
- 동일 요청 중복을 방지하고 전체 AI 자문은 단일 프로세스 내부 runner에서 기본 1개씩 실행합니다.
  대기·실행 수는 상태 화면에 표시하며 외부 worker나 queue 서비스는 추가하지 않습니다.
- 8개 자문 유형은 각각 전용 한국어 표·모바일 카드·단위·상태 배지·SEC 공시 링크·AI 설명과 근거 ID를 표시합니다. `partial`, `limited`, `data-limited`, `insufficient_data` 상태와 N-PORT 공시 지연 안내를 결과보다 먼저 표시합니다.
- 브라우저 새로고침 복원을 위해 `sessionStorage`에는 활성 자문 job ID만 저장합니다. API 토큰, 요청 입력, 분석 결과는 추가 저장하지 않습니다.
- 기능 카드를 선택하면 해당 카드 바로 다음에 요청 폼이 열립니다. 최소 시가총액, 조회 기간,
  AI 테마, 최소 분배수익률, 사용자 섹터 프록시를 선택적으로 지정할 수 있습니다.
- 일반적인 방법론 주의사항만으로 결과 전체가 `partial`이 되지 않도록 종목별 필수 데이터 상태를
  기준으로 판정합니다. `partial`은 일부 지표 제한 안내로 표시하고, 전체 필수 근거가 부족한
  `data-limited`·`insufficient_data`는 강한 경고를 유지합니다.
- 애플리케이션 기본 OpenAI 모델은 `gpt-5.6-luna`이며 `settings.ai_model`, `OPENAI_MODEL`,
  Pydantic 기본값 순서로 해석합니다.
- 프런트 페이지는 `React.lazy`로 분리해 최초 번들에 모든 화면을 한꺼번에 포함하지 않습니다.

2026-07-17 Bundle B·C 운영 검증에서는 기본 미국 주식 15개와 ETF 10개를 사용해 8개 자문 유형이 모두 완료되고 OpenAI 설명과 추적 가능한 evidence가 저장되는 것을 확인했습니다. 실행 중인 대규모 자문 job의 `updated_at` heartbeat가 전진한 뒤 Oracle 백엔드를 재시작했으며, 동일 job이 분석 1건만 생성하고 완료 상태로 복구되었습니다. 재시작 후 AAPL SEC 분석은 기존 85개 accession payload를 변경하거나 추가 다운로드하지 않고 최신 10-K·10-Q·8-K를 다시 제공했습니다. GitHub CI, Pages, Oracle 배포와 실제 Pages 정적 번들의 전용 결과·재시도·N-PORT 경고·active job 복원 코드도 확인했습니다.
