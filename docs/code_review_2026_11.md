> 이 문서는 AI(Claude Code)가 작성한 코드 리뷰 결과 보고서입니다. 사람의 검토를 거쳐 활용하세요.

# AlphaPilot 전체 코드 리뷰 및 수정 결과 (2026-11-04)

## 1. 범위와 방법

- 범위: `backend/app`(약 2.6만 줄), `frontend/src`(약 1.2만 줄), `scripts/`, 마이그레이션.
- 방법: 영역별 5개 리뷰(백엔드 코어·리포트/시세·AI 자문·원장/Toss/연구·프론트엔드)를 병렬로 수행하고,
  보고된 항목을 코드와 기존 테스트로 다시 확인했습니다. 수정한 버그에는 회귀 테스트를 추가했고,
  새 테스트는 가능한 경우 수정 전 코드에서 실패하는지도 확인했습니다.
- 검증: `pytest backend/tests`(868 passed, 31 skipped), 로컬 일회용 PostgreSQL의 DB 권한 테스트
  (`DATABASE_ACCESS_TEST_PSQL`, 23 passed), `ruff check .`, `black --check .`,
  `npm run lint`·`format:check`·`test`(150 passed)·`build`.

## 2. 수정한 버그

### 백엔드 코어 (`fix(backend)`)

| 문제 | 영향 | 수정 |
|---|---|---|
| Supabase 업데이트가 `updated_at`을 갱신하지 않음(트리거 없음) | 20분 넘게 실행 중인 리포트 작업이 polling 시 `stale_active_job`으로 실패 처리 | 업데이트마다 `updated_at` 기록 |
| 환율 갱신이 settings 행 전체를 다시 저장하거나, 행이 없을 때 일부만 insert | 동시에 저장한 사용자 설정이 되돌아가거나 SQL 기본값이 `.env`보다 우선 | 기존 행에는 `usd_krw_rate`만 저장, 첫 저장은 해석된 전체 설정 저장 |
| `POST /api/settings`가 `created_at/updated_at`을 다시 저장 | 첫 저장 시 NULL, 이후 `updated_at` 고정 | 타임스탬프 제외 |
| 레거시 `OPENAI_MODEL` 업그레이드가 시작 시 `app.state`에만 적용 | 리포트·설정 화면과 상태 화면의 모델이 달라짐 | `get_env_application_defaults()`에서 일괄 적용 |
| INSERT/RPC가 응답 타임아웃 후에도 재시도됨 | 리포트·전략·작업·원장 행 중복 가능 | 요청 미전송 오류만 재시도 |
| 페이지 조회 시 offset/limit 파라미터 누적 | 페이지네이션 오동작 가능 | 페이지마다 기본 파라미터 복원 |
| 잘못된 UUID 경로 → 500, 500 응답에 CORS 헤더 없음 | 브라우저가 네트워크 오류로 오인하고 재시도 | 404 처리, 500에도 CORS 헤더 |
| 리포트 작업 준비 단계 예외 시 작업이 active로 남음 | 다음 생성이 막힘 | `internal_error`로 실패 처리 |
| 알림 상태 저장 실패가 나머지 알림 처리 중단 | Telegram 알림 누락 | 상태 저장을 best-effort로 변경 |
| `SCHEDULER_SECRET == API_ACCESS_TOKEN`이면 사용자 토큰으로 스케줄러 호출 가능 | 보안 규칙 위반 | 스케줄러 엔드포인트 fail-closed(401) |

### 시세·리포트 (`fix(market-data)`)

- 여러 스레드의 pykrx 호출이 `logging.disable` 저장/복원을 서로 덮어써 **프로세스 전체 로그가 꺼질 수 있던 경쟁 조건** 수정.
- `ETF` + KRX 종목코드(`069500`, `069500.KS`)가 yfinance로 조회되어 항상 stale이던 문제와, 원화 ETF에 USD 환율이 곱해지던 문제 수정.
- 공급자가 같은 날짜 봉을 중복 반환하면 현재가 계산이 실패하던 문제 수정.
- 데이터 지연 판정을 UTC가 아닌 시장 현지 날짜 기준으로 변경(AGENTS.md 규칙).
- yfinance/pykrx HTTP 계층의 연결·타임아웃 오류가 재시도되지 않던 문제 수정.
- 잘린 JSON 응답도 AI 검증 실패와 같이 1회 재시도.

### AI 자문 (`fix(advisory)`)

- 실행 중인 자문 작업의 상태 조회가 **분석이 끝날 때까지 차단**되던 문제(스레드 풀 고갈 위험) 수정.
- SEC 메모리 캐시가 항목 수로만 제한되어 최대 수 GB까지 커질 수 있던 문제 → 총 바이트(64MB) 제한.
- 실제 N-PORT XML(`mon1Flow`~`mon3Flow` 속성)을 파싱하지 못해 자금 흐름이 항상 비어 있던 문제 수정
  (SEC 공개 filing 구조로 확인).
- 음수 기준값(FCF·EPS) 변화율 부호 반전, 진행 중인 연도를 포함한 배당 안정성 계산,
  1년 넘게 배당이 없는 펀드의 현재 수익률 표시, 일간 FRED 시리즈의 "1년 전" 값 오류,
  "aircraft/Shanghai"를 AI 언급으로 집계하던 문제, 데이터 부족 ETF를 "전량 축소"로 보이던 문제,
  음수 자본의 저부채 가점, 잘린 SEC 전송 미재시도, 뉴스 근거 날짜 누락 수정.

### 원장·연구·Toss (`fix(research)`)

- 연구용 낙폭(drawdown)이 첫 기간 손실을 무시하던 문제 수정.
- 백테스트 손절이 갭 하락 시에도 손절가로 체결되던 문제 → 더 불리한 시가 체결.
- Toss 클라이언트가 토큰 발급과 `GET /api/v1/*` 외 요청을 **전송 전에 거부**하도록 화이트리스트 추가.
- 동기화 응답에서 원본 계좌번호 제거, 명세서 매핑 JSON의 중복 키 거부.

### 프론트엔드 (`fix(frontend)`)

- 리포트 본문 정리 정규식이 `005930.KS` 같은 티커와 `[ETF 집중 주의]` 같은 일반 대괄호 문구를 지우던 문제 수정.
- 성과 로그를 티커만으로 연결해 과거 리포트에 다른 리포트의 성과가 표시되던 문제 → 리포트 ID 기준.
- 포커스 복귀 시 선택한 리포트가 초기 리포트로 바뀌던 문제, 작업 완료 시 중복 새로고침,
  재시도 후에도 남는 오류 배너, 비교·자문 화면의 늦게 도착한 응답이 최신 선택을 덮어쓰던 문제 수정.
- 알 수 없는 베타·상관계수가 `0`으로 보이던 문제, 비운 숫자 설정이 `0`으로 저장되던 문제 수정.
- 자산 삭제 확인, 알림 읽음 실패 처리, 배포 후 사라진 페이지 청크 복구, 서비스워커의 API 캐시 방지.

## 3. 리팩토링 (동작 변경 없음)

- 사용되지 않는 코드 제거: `upsert_external_asset`(원자적 Toss 동기화를 우회할 수 있던 경로),
  `get_candidate_asset`, `INFRASTRUCTURE_ENV_KEYS`, `_build_queries`, `_normalize_ticker`.
- 공통화: `utc_now_iso`, 평가 run 검증 로직, 자문 capability 상태 helper, `margin_pct`·`finite_number`,
  원장 canonical digest, 프론트엔드 성과 로그 매칭·티커 검증. 모듈 내부 전용 export 제거.

## 4. 수정하지 않고 결정이 필요한 항목

아래 항목은 리뷰에서 문제로 확인했지만, 측정 정책·사전등록(preregistration)·운영 결과에 영향을 주므로
임의로 바꾸지 않았습니다.

1. **기술 점수 엣지 케이스** — 가격이 변하지 않으면 RSI가 100, 거래량이 0이거나 없어도 거래량 점수 5점.
   `technical_analysis_service.py`는 `challenger_research.py`에 SHA-256으로 고정된 champion 소스라서
   수정하면 새 사전등록이 필요합니다(실제로 수정 시 챌린저 연구 테스트 7건이 실패해 되돌렸습니다).
2. **추천 사이클 목표/손절 갱신** — 같은 사이클을 재사용할 때 목표가·손절가를 최신 값으로 덮어써,
   5% 미만 변경이 누적되거나 과거 봉을 나중 목표로 다시 평가할 수 있습니다. 현재 동작은
   `test_decision_lineage.py`가 명시적으로 검증하는 2026-09-11 정책이므로 유지했습니다.
3. **horizon 변경 시 기존 활성 사이클 유지** — 같은 종목에 두 horizon 사이클이 동시에 활성화됩니다.
4. **백테스트 연환산** — N개 표본 기간을 N−1 구간으로 계산해 연환산 값이 과대 추정될 수 있습니다(연구 방법론 결정).
5. **SEC 공시 위험 등급** — "liquidity", "litigation" 키워드가 거의 모든 10-K/10-Q에 있어 대부분 `high_risk`로 분류됩니다.
6. **Vite 버전** — AGENTS.md는 Vite 5.x, `package.json`은 `^6.4.3`입니다.

### 검토 결과 의도된 동작으로 판단한 항목

- 원장 replay/review가 이후 날짜로 정정된 revision을 기준일 시점에는 이전 revision으로 처리하는 것은
  `test_future_effective_revision_does_not_hide_historical_duplicate`가 검증하는 유효일(effective-dated) 모델입니다.

### 낮은 우선순위 개선 후보

- `/docs`·`/openapi.json` 공개, 중복 요청에도 일일 생성 한도 차감, 만료 토큰 시 잠금 화면 미복귀.
- 대기 중인 자문 작업은 heartbeat가 없어 20분 이상 대기하면 만료될 수 있음.
- `list_reports` 등 무제한 조회가 PostgREST 1,000행 상한에 걸릴 수 있음, `/api/performance-logs`의 전략 전체 조회.
- 국내 후보군 갱신 시 순위 밖 종목 비활성화 미처리, stale 지수 점수 표시, 수동 스냅샷 날짜(UTC) 기준 차이.
- 자문 provider 호출의 `TypeError` 폴백이 내부 오류를 숨김, ETF 보유종목 ROE 백분율 휴리스틱.
