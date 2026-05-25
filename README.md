# AlphaPilot

AlphaPilot은 1인 사용자를 위한 개인 AI 투자 의사결정 지원 MVP입니다. 사용자의 자산을 저장하고,
한국 및 미국 시장 데이터를 가져오며, 기술적 지표를 계산하고, 국내/글로벌 전략 리포트를 생성합니다.
생성된 리포트와 전략 성과 로그는 Supabase에 저장됩니다.

이 앱은 자동 매매를 하지 않습니다. 브로커 API에 연결하지 않으며, 주문 실행 기능도 없습니다.

## 아키텍처

```text
사용자 브라우저
  -> GitHub Pages React 프론트엔드
  -> Render Free FastAPI 백엔드
  -> Supabase PostgreSQL

GitHub Actions
  -> /health 웜업
  -> 예약 리포트 생성 엔드포인트 호출

백엔드 데이터/AI 제공자
  -> pykrx: 한국 시장 데이터
  -> yfinance: 미국 시장 데이터
  -> OpenAI API: 리포트 추론
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

```bash
cd frontend
npm install
npm run dev
```

Supabase 설정이 없으면 백엔드는 로컬 메모리 저장소로 동작합니다. 따라서 Supabase를 만들기 전에도
API와 화면을 간단히 확인할 수 있습니다. 실제 배포 환경에서는 Supabase 설정이 필요합니다.

## 백엔드 환경 변수

인프라 비밀값과 배포 값은 환경별로 반드시 설정해야 하며, 앱 기본값을 갖지 않습니다.

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

애플리케이션 기본값은 `.env`에서 선택적으로 설정할 수 있습니다. 런타임 우선순위는 다음과 같습니다.

1. `settings` 테이블의 값
2. `.env` 값
3. Pydantic 모델 기본값

```text
DOMESTIC_REPORT_TIME=08:30
GLOBAL_REPORT_TIME=22:30
AI_PROVIDER=openai
OPENAI_MODEL=gpt-5.4-mini
RISK_PROFILE=balanced
FRONTEND_TIMEZONE=Asia/Seoul
STALE_DATA_BUSINESS_DAYS=2
```

OpenAI 공식 모델 문서에는 `gpt-5.4-mini`가 등록되어 있습니다. 실제 운영 전에 본인의 OpenAI
프로젝트에서 해당 모델을 사용할 수 있는지 확인하세요. 모델은 `OPENAI_MODEL` 또는
`settings.ai_model`로 변경할 수 있습니다.

## 프론트엔드 환경 변수

```text
VITE_API_BASE_URL=http://localhost:8000
VITE_API_ACCESS_TOKEN=change-this-user-token
```

`VITE_API_ACCESS_TOKEN`은 단일 사용자 MVP용 가벼운 접근 제어입니다. 이 값은 프론트엔드 번들에
포함되므로, 배포된 프론트엔드에 접근할 수 있는 사람은 값을 확인할 수 있습니다. 이 MVP를 다중 사용자
서비스나 production-grade 인증으로 간주하면 안 됩니다.
GitHub Pages 저장소가 public이면 URL을 아는 사람이 화면에 접근하고 자산/리포트 데이터를 볼 수
있다고 가정해야 합니다.

프론트엔드에는 OpenAI 키, Supabase 키, 시장 데이터 자격 정보, `SCHEDULER_SECRET`을 넣지 마세요.

## Supabase 설정

1. Supabase 프로젝트를 만듭니다.
2. Supabase SQL editor에서 `backend/app/db/migrations/001_initial_schema.sql`을 실행합니다.
3. Render 환경 변수에 `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`를 설정합니다.

Supabase service role key는 RLS를 우회합니다. 반드시 서버 사이드에만 보관하고, 프론트엔드나
사용자에게 보이는 에러 메시지에 노출하지 마세요.

## Render 배포

백엔드는 Render Free에 배포합니다. `backend/render.yaml`에 웹 서비스 설정이 들어 있습니다.
Render에는 필수 환경 변수를 모두 설정해야 하며, `FRONTEND_ORIGIN`은 GitHub Pages 프론트엔드
URL로 지정합니다.

Render Free는 유휴 상태가 지속되면 잠들 수 있습니다. GitHub Actions 예약 워크플로는 리포트 생성
전에 `/health`를 호출해 백엔드를 웜업합니다.

## GitHub Pages 배포

`.github/workflows/pages.yml`은 `frontend/`를 빌드해서 GitHub Pages로 배포합니다. GitHub Secrets에
다음 값을 설정하세요.

```text
VITE_API_BASE_URL
VITE_API_ACCESS_TOKEN
```

## GitHub Actions 스케줄러

저장소 Secrets에 다음 값을 설정하세요.

```text
BACKEND_URL
SCHEDULER_SECRET
```

국내 리포트 스케줄:

```text
30 23 * * 0-4
```

글로벌 리포트 스케줄:

```text
30 13 * * 1-5
```

GitHub Actions 예약 실행은 best-effort입니다. GitHub 부하에 따라 몇 분에서 수십 분 늦어질 수
있습니다. 글로벌 리포트는 고정된 `13:30 UTC` 스케줄을 사용하며, 미국 서머타임에 자동 대응하지
않습니다. 필요하면 1년에 두 번 cron 값을 수동 조정하세요.

## 수동 리포트 생성 테스트

Render와 Supabase 설정 후 다음 명령으로 테스트할 수 있습니다.

```bash
curl -fsS -X POST "$BACKEND_URL/api/reports/domestic/generate" \
  -H "Authorization: Bearer $SCHEDULER_SECRET"

curl -fsS -X POST "$BACKEND_URL/api/reports/global/generate" \
  -H "Authorization: Bearer $SCHEDULER_SECRET"
```

GitHub Actions 화면에서 각 리포트 워크플로의 `workflow_dispatch`를 직접 실행해도 됩니다.

## 보안 범위

이 MVP는 단일 사용자 전용입니다. 로그인, Supabase Auth, 사용자 테이블, 테넌트 분리,
production-grade 인증은 없습니다. 모든 `/api/*` 엔드포인트는 `API_ACCESS_TOKEN`이 필요하며,
리포트 생성 엔드포인트만 `SCHEDULER_SECRET`을 사용합니다.

리포트 생성 엔드포인트는 UTC 기준 하루에 엔드포인트별 10회로 제한됩니다. 이 제한은 앱 프로세스
메모리에서 동작하므로, 백엔드 프로세스가 재시작되면 카운터가 초기화됩니다.

## MVP 제한 사항

- 자동 매매 없음
- 수익 보장 없음
- 무료 시장 데이터는 지연되거나 불완전할 수 있음
- AI 리포트 품질은 입력 데이터 품질에 의존함
- 뉴스 수집은 승인된 제공자가 추가되기 전까지 범위 밖
- 보유 자산 외 `추가 매수 후보`는 코드에 고정된 기본 후보군을 pykrx/yfinance 가격 데이터와
  기술 점수로만 선별함
- 추가 매수 후보는 투자 아이디어이며 수익을 보장하지 않음. 실제 매수 전에는 비중, 손절 기준,
  포트폴리오 집중도를 별도로 확인해야 함
- Render Free는 유휴 상태에서 잠들 수 있음
- GitHub Actions 스케줄은 정확한 실행 시간을 보장하지 않음
- 글로벌 cron은 미국 서머타임에 자동 대응하지 않음
- 백테스팅은 이번 MVP 범위에서 제외됨

## 구현 가정

- 기술 점수는 AGENTS.md의 가중치를 그대로 사용합니다. 다만 AGENTS.md가 세부 하위 점수 공식을
  정의하지 않아, MVP에서는 `backend/app/services/technical_analysis_service.py`의 단순하고 투명한
  임계값 규칙을 사용합니다.
- `performance_logs`에는 market 필드가 없으므로, 백필 시 숫자형 티커는 KR, 그 외는 US로 추정합니다.
- 포트폴리오 요약에서 현재 시장 데이터를 가져오지 못하면, 화면 표시를 유지하기 위해 평균 매입가를
  로컬 fallback으로 사용합니다.
- 추가 매수 후보군은 MVP용 고정 목록입니다. 새 뉴스/시장 데이터 제공자를 추가하지 않기 위해 후보군
  자동 탐색, 스크리닝 API, 스크래핑은 사용하지 않습니다.

## 품질 확인 명령

```bash
pytest backend/tests -v
ruff check .
black --check .
```
