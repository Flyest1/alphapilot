# AlphaPilot 코드 전체 검토 보고서 (2026-06)

이 문서는 고도화(Post-MVP → v2) 개발에 앞서 수행한 전체 코드 검토 결과입니다.
개선 계획은 `docs/development_plan_v2.md`를 참고하세요.

---

## 1. 전체 구조 요약

```text
backend/   FastAPI (Python 3.10)  약 3,600줄 (앱) + 1,700줄 (테스트)
frontend/  React 18 + Vite 5      약 3,100줄 (JSX) + 1,300줄 (CSS)
docs/      AGENTS.md(지침서), post_mvp_roadmap.html
.github/   domestic_report.yml, global_report.yml, pages.yml
```

- 배포: GitHub Pages(프론트) + Render Free(백엔드) + Supabase(DB) + GitHub Actions(스케줄러)
- 보안: 단일 사용자 토큰 게이트(`API_ACCESS_TOKEN`) + 스케줄러 시크릿(`SCHEDULER_SECRET`)
- Post-MVP Phase 1~3(리포트 잡 영속화, 포트폴리오 스냅샷, 추천 사이클 추적) 구현 완료

## 2. 잘 되어 있는 부분 (유지할 강점)

| 영역 | 내용 |
|---|---|
| 백엔드 계층화 | api / services / models / db / utils 분리가 명확함 |
| 의존성 주입 | 서비스 생성자 주입으로 테스트 가능 구조 (`ReportService.__init__`) |
| 백엔드 테스트 | 17개 테스트 파일, 핵심 서비스/인증/CRUD 커버 (외부 호출 mock) |
| 장애 격리 | 외부 API 실패 시 `log_external_failure` + data-limited 폴백, LLM 실패 시 technical-only 리포트 폴백 |
| 재시도 | tenacity 기반 시장 데이터 재시도, LLM 스키마 검증 실패 시 1회 재시도 |
| 스키마 강제 | `ReportContent` pydantic `extra="forbid"` 로 LLM 출력 검증 |
| 프론트 캐싱 | localStorage 기반 GET 캐시(5분)로 Render 콜드스타트 체감 완화 |
| 반응형 CSS | 900px/640px 분기, 모바일 카드 뷰 전환 |

## 3. 주요 리팩토링 대상 (문제점)

### 3.1 백엔드

1. **`report_service.py` 갓 클래스 (1,140줄)** — `backend/app/services/report_service.py`
   - 한 클래스가 설정 로드, 환율 갱신, 보유/후보 분석, 후보 스크리닝, 지수 분석, 뉴스 컨텍스트,
     AI 호출, 폴백 리포트, stale 규칙, 저장, 성과 백필, 사이클 백필, 프롬프트까지 모두 담당.
   - 후보 유니버스(약 45종목)가 코드에 하드코딩 (`CANDIDATE_UNIVERSE`).
   - 프롬프트가 한 개의 거대 문자열(`_prompt`)로 관리됨 — 버전 관리/실험 불가.
2. **중복 유틸** — `_normalize_ticker`/`_infer_market`/`_trend_label`/`_action_label` 이
   `report_service.py`, `strategy_service.py`, `market_data_service.py` 에 중복 정의.
   `_infer_market` 은 6자리 영숫자 휴리스틱이라 일부 미국 티커 오분류 가능.
3. **동기 블로킹 파이프라인** — 리포트 생성이 요청 스레드에서 순차 실행(자산 분석만 ThreadPool 5개).
   Render Free 단일 워커에서 생성 중 다른 API 응답 지연.
4. **시장 데이터 캐시 휘발성** — `MarketDataService._price_cache` 가 프로세스 메모리 dict.
   Render 콜드스타트마다 소실되고, 백필 시 종목당 매번 재호출(yfinance rate limit 위험).
5. **고정 비율 리스크 산정** — `strategy_service.py` 손절/목표가가 성향별 고정 %(예: balanced 8%).
   종목 변동성(ATR)과 무관해 변동성 큰 종목에서 손절이 과도하게 잦거나 둔감함.
6. **백필 비효율** — `backfill_performance_logs`(250건)·`backfill_recommendation_cycles`(500건)가
   리포트 생성마다 전체 루프 + 종목당 가격 이력 재조회. 데이터가 쌓일수록 리포트 생성이 느려짐.
7. **레이트리미터 휘발성** — `DailyEndpointRateLimiter` 인메모리(일 10회). 재시작 시 초기화.
8. **`supabase_client.py` (533줄)** — Repository 한 클래스에 9개 테이블 CRUD가 평면 나열.
   테이블별 모듈 분리 또는 제네릭 헬퍼로 축소 여지.

### 3.2 프론트엔드

1. **갓 컴포넌트** — `Reports.jsx`(796줄), `Dashboard.jsx`(403줄)에 API 호출, 폴링, 필터링,
   포매팅, 렌더링이 모두 포함.
2. **포매터 중복** — `formatValue`/`formatReturn` 류 함수가 `Reports.jsx`, `StrategyTable.jsx`,
   `KeyMessageList.jsx` 등 3곳 이상에 복붙.
3. **차트 수작업** — `Comparison.jsx` SVG 폴리라인, 대시보드 CSS 막대를 직접 구현.
   확장(줌, 다중 시리즈, 접근성)이 어렵고 모바일에서 min-width 720px 문제.
4. **에러 복구 부재** — ErrorBoundary 없음, 잡 폴링 실패 시 무한/무반응 가능, 재시도 버튼 없음,
   스켈레톤 로더 없음.
5. **프론트 테스트/린트 0개** — 테스트 라이브러리, ESLint, Prettier 미설정.
6. **접근성** — aria-label 누락, 포커스 트랩 없음, SVG 차트 대체 텍스트 없음.
7. **문자열 하드코딩** — UI 문자열 100여 개가 JSX에 산재 (단일 사용자 한국어 전용이므로
   i18n 도입은 보류 가능하나, 상수화는 필요).

### 3.3 인프라/품질

1. **CI 부재** — pytest/ruff/black/npm build 를 강제하는 GitHub Actions 워크플로 없음
   (Pages 배포 워크플로만 존재). 지침서의 "Test before commit"이 수동 규율에만 의존.
2. **글로벌 리포트 cron** — 미국 서머타임 미보정 (지침서에 한계로 명시됨, 개선 여지).
3. **마이그레이션 수동 실행** — SQL Editor 수동 적용. 적용 여부를 코드가 검증하지 않음.

## 4. 보안 검토

- 토큰 비교가 단순 문자열 비교(`main.py:79`) — 타이밍 공격 노출은 낮은 위험이나
  `secrets.compare_digest` 권장.
- localStorage 토큰 보관은 지침서에 명시된 MVP 한계. Phase 7 결정 필요.
- CORS는 단일 오리진 화이트리스트로 적절. 서비스 롤 키는 서버 전용으로 유지됨. 양호.
- 레이트리밋은 수동 생성 엔드포인트에만 적용 — 전체 API에 기본 한도 부여 검토.

## 5. 데이터/도메인 검토 (수익 관점)

1. **추천 성과 데이터는 쌓이지만 활용되지 않음** — `recommendation_cycles` 에
   1d/5d/20d/60d 수익률과 hit_target/hit_stop 결과가 축적되는데, 이를 신뢰도 보정·승률 표시·
   전략 파라미터 개선에 쓰는 코드가 없음. **가장 큰 미활용 자산.**
2. **신뢰도(confidence)가 사실상 기술 점수 ±5** — 과거 적중률과 무관해 사용자에게 주는 정보가 낮음.
3. **후보 스크리닝이 정적 유니버스 + 기술 점수 컷** — 시장 전체 스크리닝(pykrx 전 종목 OHLCV,
   yfinance 유니버스 확장)이 가능함에도 45종목 하드코딩에 머묾.
4. **환노출/섹터/집중도 분석 부재** — 지침서 Phase 4에 계획만 존재.
5. **세금·수수료 미반영** — 국내 거래세, 미국 양도세/환전 스프레드가 수익률 계산에 없음.

## 6. 결론

코드베이스는 MVP로서 완성도가 높고(특히 백엔드 폴백/테스트), 구조적 부채는
`report_service.py` 와 프론트 갓 컴포넌트 2곳에 집중되어 있습니다.
고도화의 핵심 기회는 **이미 축적 중인 추천 사이클 성과 데이터를 신뢰도 보정과
의사결정 지원으로 되먹임하는 것**이며, 리팩토링은 그 전제 작업으로 선행해야 합니다.
