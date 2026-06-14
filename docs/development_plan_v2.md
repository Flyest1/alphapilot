# AlphaPilot 고도화 개발 계획서 v2 (2026-06)

목적: MVP 수준에 머무르지 않고, **사용자 편의성**과 **투자 수익 극대화**를 위한
리팩토링 + 기능 고도화 로드맵을 정의합니다.

- 전제가 되는 코드 검토 결과: `docs/code_review_2026_06.md`
- 본 계획 확정과 함께 `AGENTS.md`(지침서)가 개정되었습니다. 개정 내역은 9장 참조.

> 용어 정리: 본 문서의 "수익 극대화"는 지침서의 제품 철학
> `Return optimization = expected return × probability − downside/volatility/concentration/liquidity risk`
> 에 따라 **사용자의 투자 수익률 극대화(의사결정 품질 향상)** 를 의미합니다.
> 서비스 자체의 상업화(멀티유저/과금)는 선택 트랙 C(별도 승인 필요)로 분리했습니다.
> 자동 매매·주문 실행 금지 원칙은 변하지 않습니다.

---

## 1. 전체 트랙 구성

```text
트랙 R (선행) : 구조 리팩토링 + 품질 인프라          — 기능 추가의 전제
트랙 A        : 수익 극대화 기능 (Phase 4, 5, 8)      — 분석 신뢰도, 의사결정 지원, 신호 품질
트랙 B        : 사용자 편의성 기능 (Phase 6, 9)       — 모바일/PWA, 오늘의 액션, 알림 센터
트랙 C (선택) : 보안 상향(Phase 7), 멀티유저/상업화(Phase 10) — 사용자 결정 필요
```

실행 순서: **R1 → R2 → R3 → Phase 4 → Phase 5 → Phase 6 → Phase 8 → Phase 9 → (결정 시) 7/10**

---

## 2. 트랙 R: 리팩토링 (선행 작업)

### R1. 백엔드 구조 분해

`report_service.py`(1,140줄)를 책임 단위로 분리한다. 공개 API·동작은 변경하지 않는다(동작 보존 리팩토링).

```text
backend/app/services/report/
  pipeline.py          # ReportService: 단계 오케스트레이션만 담당
  candidate_screener.py# 후보 유니버스/호라이즌 스코어링 (CANDIDATE_UNIVERSE → DB seed로 이전)
  prompt_builder.py    # 프롬프트 조립 (섹션별 함수, 버전 상수)
  persistence.py       # _save_report / 스냅샷 / 전략 저장
  tracking.py          # performance_logs · recommendation_cycles 백필/사이클 동기화
backend/app/utils/tickers.py  # normalize_ticker / infer_market 단일화
backend/app/utils/labels.py   # action/trend/risk 한국어 라벨 단일화
```

- 백필 최적화: 평가 미완료(`price_after_20d IS NULL` 등) 행만 조회하도록 Repository 쿼리 추가,
  같은 티커 가격 이력은 1회만 조회해 재사용.
- 토큰 비교를 `secrets.compare_digest` 로 교체 (`main.py`).
- 시장 데이터 일중 캐시를 Supabase `market_data_cache` 테이블(추가 마이그레이션)로 영속화해
  콜드스타트 후 재호출 폭주 방지. (additive migration)

### R2. 프론트엔드 구조 분해

- `src/utils/formatters.js` 신설 → `formatValue`/`formatReturn`/`formatPercent` 중복 제거.
- `Reports.jsx` 분해: `ReportSelector`, `ReportContent`, `StrategyFilters`, `PerformancePanel`.
- `Dashboard.jsx` 분해: `SummaryCards`, `AllocationChart`, `TrendChart`, `TopStrategies`.
- `App.jsx` 에 ErrorBoundary + 페이지별 재시도 버튼, 공통 스켈레톤 로더.
- API 클라이언트에 타임아웃/재시도(콜드스타트 1회 재시도) 및 표준 에러 객체 도입.
- UI 문자열을 `src/constants/strings.js` 로 상수화 (i18n 라이브러리는 도입하지 않음).

### R3. 품질 인프라

- 프론트: Vitest + React Testing Library, ESLint + Prettier 도입 (지침서 개정 반영).
  최소 범위: formatters, api client, StrategyTable, 필터 로직.
- CI 워크플로 `.github/workflows/ci.yml` 신설: pytest / ruff / black --check / npm lint / npm test / npm build.
- 차트 라이브러리 Recharts 도입 승인 (지침서 개정 반영) → `Comparison.jsx` SVG 수작업 차트 대체,
  모바일 반응형·툴팁·접근성 개선.

완료 기준: 기존 pytest 전체 통과 + 신규 프론트 테스트 통과 + CI 녹색 + 기능 동일성 수동 확인.

---

## 3. 트랙 A — Phase 4: 분석 신뢰도와 성과 되먹임 (수익 극대화 1단계)

목표: 축적 중인 `recommendation_cycles` 성과 데이터를 **신뢰도 보정과 투명성**으로 되먹임한다.
현재 confidence는 기술 점수 ±5라 정보가치가 낮다 — 이것을 실측 승률 기반으로 바꾸는 것이 핵심.

### 4-1. 추천 성과 통계 API/화면

- `GET /api/recommendation-stats`: 액션×호라이즌×점수밴드(60대/70대/80+)별
  승률(hit_target 비율), 평균 5d/20d 수익률, 표본 수, 평균 보유일.
- `비교` 탭 옆 신규 `성과 분석` 화면: "BUY·medium·점수 70대 추천의 20일 승률 64% (표본 22건)" 식 표시.

### 4-2. 신뢰도 보정 (calibrated confidence)

- 표본 30건 이상인 밴드부터 `confidence = 기술점수 기반 점수 × 실측 승률 보정계수`.
- 표본 부족 시 기존 방식 유지 + "보정 전(표본 부족)" 배지 표시.
- 전략 카드에 신뢰도 산출 근거(기술 기여 / 과거 승률 기여 / 뉴스 기여)를 분해 표시.

### 4-3. 노출/집중도 분석

- 포트폴리오 요약에 통화(KRW/USD)·시장(KR/US/ETF/CASH)·섹터(yfinance `info.sector`,
  pykrx 업종) 노출 비중 추가. 단일 종목 25%↑, 단일 섹터 40%↑ 시 집중도 경고.
- 신규 스키마: `assets`/`candidate_assets` 에 `sector` 컬럼 (additive), 리포트 생성 시 자동 보충.

### 4-4. 데이터 품질 배지

- 전략 카드/테이블에 데이터 신선도(최근 거래일), 제공자, 뉴스 컨텍스트 유무 배지 표시.
- 리포트 입력 스냅샷(`report_inputs` JSONB, additive)을 리포트와 함께 저장해 사후 검증 가능하게.

## 4. 트랙 A — Phase 5: 포트폴리오 의사결정 지원 (수익 극대화 2단계)

자동 실행 없는 의사결정 지원만 제공한다 (주문/브로커 연동 금지 유지).

### 5-1. 변동성 기반 리스크 산정 (StrategyService 개선)

- 고정 % 손절/목표가를 **ATR(14) 기반**으로 교체:
  `stop = price − k×ATR`, `target = price + m×ATR` (k, m은 위험 성향별 계수).
- ATR은 기존 `technical_analysis_service.py` 에 pandas/numpy로 직접 구현 (외부 TA 라이브러리 금지 유지).

### 5-2. 목표 배분과 리밸런스 제안

- 설정에 목표 배분(국내/글로벌/현금 %, 종목별 상한 %) 추가 — `settings` 테이블 additive 컬럼.
- 대시보드에 `목표 대비 드리프트` 카드: 임계치(기본 5%p) 초과 시 "비중 축소/확대 검토" 제안 문구.
- 리포트 생성 시 LLM 컨텍스트에 목표 배분·드리프트를 포함해 `allocation_comment` 품질 향상.

### 5-3. 포지션 사이징 가이드 (의사결정 지원)

- 신규 매수 후보에 "제안 투입 한도" 표시: `min(가용 현금 × 성향별 비율, 1회 리스크 한도 ÷ (진입가 − 손절가))`
  방식의 고정 리스크(fixed-fractional) 계산. 주문 수량/티켓은 표시하지 않고 금액 범위만 안내.

### 5-4. 세금·비용 인지 수익률

- 설정에 수수료율/거래세율(국내), 환전 스프레드 입력 → 성과 화면에 "세후·비용 차감 추정 수익률" 병기.

## 5. 트랙 A — Phase 8: 신호 품질 엔진 (수익 극대화 3단계)

상태: 구현 완료 (2026-06). `012_create_candidate_universe.sql` 적용 필요.

- **후보 유니버스 확장**: 하드코딩 45종목 → `candidate_universe` 테이블(seed 마이그레이션)로 이전,
  pykrx 시가총액 상위 N / yfinance 주요 ETF 구성으로 주기 갱신(스케줄러 잡, 외부 서비스 불필요).
- **룰 백테스트 검증**: 기술 점수 → 액션 규칙을 과거 가격 이력으로 검증하는
  `backtest_service`(오프라인, 리포트 생성과 분리). 결과는 `성과 분석` 화면에
  "이 규칙의 과거 20일 평균 수익률/승률"로 표시. *시뮬레이션이며 실행이 아님을 명시.*
- **배당/실적 캘린더**: yfinance `calendar`/`dividends` 범위 내에서 보유 종목 이벤트를
  리포트 리스크/기회 섹션과 대시보드에 표시 (신규 외부 서비스 불필요).

## 6. 트랙 B — Phase 6: 사용자 편의성 (UX 고도화)

- **오늘의 액션 브리핑**: 대시보드 최상단에 "오늘 확인할 것" 카드 —
  손절/목표가 도달 종목, 드리프트 경고, 신규 BUY 후보, 데이터 지연 종목을 한 줄씩 요약.
- **리포트 diff 뷰**: 직전 리포트 대비 액션 변경(HOLD→REDUCE 등), 신뢰도 변화, 신규/제외 후보 강조.
- **모바일 리포트 카드**: 테이블 → 스와이프 가능한 카드 우선 UI, 정렬(신뢰도/수익률) 지원.
- **PWA**: manifest + 서비스워커(정적 자산 + 마지막 리포트 캐시) → 설치형, 오프라인 마지막 리포트 열람.
  외부 서비스 불필요 범위만. (Web Push는 Phase 9에서 별도 결정)
- **CSV 자산 가져오기/내보내기**: 증권사 CSV 업로드로 자산 일괄 등록, 백업용 내보내기.
- **Recharts 차트 전환**: 비교/대시보드 차트 반응형·툴팁·기간 줌.

## 7. 트랙 B — Phase 9: 알림 센터

상태: 구현 완료 (2026-06). `013_create_notifications.sql` 적용 및 Telegram 환경변수 선택 설정 필요.

- 인앱 알림 센터(`notifications` 테이블, additive): 리포트 생성 완료, 목표/손절 도달,
  사이클 종료(hit_target/hit_stop/expired), 드리프트 경고를 스케줄 리포트 생성 시 적재.
- 프론트 헤더에 알림 뱃지 + 목록. 읽음 처리.
- **텔레그램 봇 알림 (2026-06 승인됨)**: 동일 이벤트를 Telegram Bot API로 발송.
  `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` 환경변수, 설정 화면에서 이벤트별 on/off,
  미설정 시 조용히 건너뜀. 무료이며 모바일 푸시 효과가 즉시 확보됨.
- 이메일/Web Push 등 다른 외부 채널은 구체 제공자 확정 시 지침서 개정 후 진행.

## 8. 트랙 C (사용자 결정 필요)

### Phase 7: 보안 상향

권장안: **B. 서버측 패스워드/세션 게이트** (현 단일 사용자 유지 시 최소 변경·최대 효과).
멀티유저 전환(Phase 10) 의사가 있으면 C(Supabase Auth)를 바로 선택하는 것이 이중작업을 막는다.

### Phase 10 (선택): 멀티유저/상업화

상태: `docs/phase10_multi_user_design.md`에 설계만 작성됨. 구현 승인 전 변경 금지.

서비스 수익화(구독/과금)를 원할 경우의 전환 트랙. **착수 전 명시적 승인 + 지침서 대개정 필요.**

- Supabase Auth + 전 테이블 `user_id` + RLS, Render 유료 플랜, OpenAI 비용 사용자별 한도,
  법적 고지(투자자문업 규제 검토 — 한국에서 유사투자자문/투자자문 라이선스 이슈가 있어
  상업화 전 법률 검토가 선행되어야 함).
- 본 계획서 범위에서는 설계만 보유하고 구현하지 않는다.

---

## 9. 지침서(AGENTS.md) 개정 내역

본 계획과 함께 다음이 개정되었다:

1. Frontend 스택에 **Recharts** 허용 추가.
2. Code Quality에 **ESLint, Prettier, Vitest + React Testing Library** 추가, CI 워크플로 요구 명시.
3. Post-MVP Roadmap: Phase 4·5 상세화(성과 되먹임, ATR, 리밸런스, 포지션 사이징),
   **Phase 8(신호 품질 엔진), Phase 9(알림 센터), Phase 10(멀티유저/상업화 — 승인 필요)** 신설.
4. Development Order를 트랙 R → A → B → C 순서로 갱신.
5. Testing Requirements에 프론트엔드 테스트 최소 범위 추가.
6. **(2026-06 사용자 결정 반영)** Allowed External Services 개정:
   - 기존 허용 서비스의 유료 티어 업그레이드(Render/Supabase/OpenAI 사용량)는 단계상 필요 시 사전 승인된 것으로 간주.
   - **Telegram Bot API를 알림 채널로 허용** (Phase 9에서 구현).
   - 신규 유료 데이터 API·이메일 등은 원칙적으로 허용하되, 구체 제공자/비용은 구현 전 확정 필요.
   - 자동매매/주문 실행 금지는 사용자 확인으로 **유지**.

변경되지 않는 원칙: 자동 매매/주문/브로커 연동 금지, 수익 보장 표현 금지,
화이트리스트 외 외부 서비스 금지, additive 마이그레이션, 한국어 README.

---

## 10. 마일스톤과 검증

| 단계 | 산출물 | 검증 |
|---|---|---|
| M1 (R1–R3) | 구조 분해 + CI + Recharts 전환 | pytest/린트/빌드 CI 녹색, 기능 동일성 확인 |
| M2 (Phase 4) | 성과 통계 API/화면, 보정 신뢰도, 노출 분석 | 신규 pytest + Vitest, 표본 기반 수치 검증 |
| M3 (Phase 5) | ATR 리스크, 리밸런스 제안, 사이징 가이드 | ATR 단위 테스트, 시나리오 테스트 |
| M4 (Phase 6) | 액션 브리핑, diff 뷰, PWA, CSV | Lighthouse PWA 통과, 모바일 수동 점검 |
| M5 (Phase 8) | 유니버스 확장, 백테스트, 캘린더 | 백테스트 재현성 테스트 |
| M6 (Phase 9) | 인앱 알림 센터 | 스케줄 리포트 후 알림 적재 e2e 확인 |

각 마일스톤은 지침서의 Completion Definition(테스트, README 갱신, Conventional Commit)을 따른다.
