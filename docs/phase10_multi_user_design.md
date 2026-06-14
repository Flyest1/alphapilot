# AlphaPilot Phase 10 멀티유저/상업화 설계

상태: **설계 문서만 작성됨. 구현 승인 전까지 코드·DB·인증·배포 변경 금지.**

작성일: 2026-06-14

## 1. 목적과 경계

Phase 10의 목적은 현재 단일 사용자 투자 의사결정 지원 시스템을 여러 사용자가 안전하게
사용할 수 있는 서비스로 전환하는 것입니다.

계속 유지할 제품 경계:

- 자동 매매, 주문 실행, 브로커 API 연결을 구현하지 않습니다.
- 수익 보장, 무위험 수익, 반드시 매수/매도 같은 표현을 사용하지 않습니다.
- 투자 판단을 돕는 정보와 위험 관리 가이드만 제공합니다.

이 문서는 목표 구조와 승인 조건을 정의합니다. 다음 항목은 구현하지 않았습니다.

- Supabase Auth 로그인/회원가입
- `user_id` 컬럼, RLS 정책, 데이터 이관 migration
- 결제/구독
- 사용자별 OpenAI 비용 제한
- 멀티유저 스케줄 실행기
- 법률 검토 결과에 따른 제품 변경

## 2. 구현 전 필수 승인 게이트

다음 조건이 모두 완료되기 전에는 Phase 10 구현을 시작하지 않습니다.

1. 사용자의 명시적 Phase 10 구현 승인
2. `AGENTS.md` 대개정과 보안 모델 C(Supabase Auth) 확정
3. Supabase Auth 로그인 방식 확정
4. 기존 단일 사용자 데이터의 소유자 계정 확정
5. Render/Supabase/OpenAI 비용 계획과 사용자별 월 한도 확정
6. 멀티유저 스케줄 처리 구조 승인
7. 한국 투자자문 관련 자격을 갖춘 전문가의 법률 검토 완료
8. 개인정보 처리방침, 이용약관, 면책 문구 확정
9. 결제 기능이 필요하면 구체적인 결제 제공자와 비용 별도 승인

## 3. 목표 보안 구조

권장 인증 모델은 Supabase Auth입니다.

```text
React frontend
  -> Supabase Auth 로그인
  -> 사용자 JWT 획득
  -> FastAPI Authorization: Bearer <user JWT>
  -> JWT 검증 후 요청 사용자 식별
  -> 사용자 범위 쿼리 + Supabase RLS
```

핵심 원칙:

- 프론트엔드는 Supabase anon key만 사용합니다.
- Supabase service role key는 백엔드와 승인된 백그라운드 작업에서만 사용합니다.
- 일반 사용자 API는 service role 권한에 의존하지 않고 사용자 JWT와 RLS를 함께 검증합니다.
- 스케줄러 secret은 사용자 API 인증 수단으로 사용하지 않습니다.
- 관리자 기능은 별도 역할과 감사 로그 없이는 만들지 않습니다.
- API 응답, 로그, 알림에 다른 사용자의 데이터나 secret이 포함되지 않아야 합니다.

## 4. 데이터 모델 전환

현재 지침에 따라 모든 기존 테이블에 `user_id uuid references auth.users(id)`를 추가하는
방향으로 설계합니다. 실제 migration은 구현 승인 후 별도 검토합니다.

대상:

```text
assets
reports
strategies
settings
performance_logs
candidate_assets
report_jobs
portfolio_snapshots
recommendation_cycles
market_data_cache
candidate_universe
notifications
```

안전한 이관 순서:

1. `user_id` nullable 컬럼과 인덱스를 additive migration으로 추가
2. 기존 단일 사용자 데이터에 승인된 소유자 계정 ID를 backfill
3. 모든 repository/API 쿼리에 사용자 범위 적용
4. 테이블별 RLS 정책 추가 및 교차 사용자 접근 테스트
5. 백그라운드 작업에 명시적인 대상 사용자 ID 전달
6. 검증 완료 후에만 `user_id not null` 제약을 별도 승인받아 적용

`candidate_universe`와 `market_data_cache`를 공유 데이터로 최적화하는 방안은 현재
“모든 테이블에 user_id” 규칙과 충돌합니다. 공유 테이블로 전환하려면 구현 전에
`AGENTS.md`를 다시 개정해야 합니다.

## 5. RLS 정책 설계

기본 정책은 모든 사용자 소유 테이블에서 다음 조건을 강제합니다.

```sql
auth.uid() = user_id
```

정책 매트릭스:

| 테이블 범주 | SELECT | INSERT | UPDATE | DELETE |
|---|---|---|---|---|
| 사용자 입력 자산/설정 | 본인 행 | 본인 `user_id` | 본인 행 | 본인 행 |
| 리포트/전략/성과/스냅샷 | 본인 행 | 백엔드 작업만 | 백엔드 작업만 | 기본 금지 |
| report_jobs/notifications | 본인 행 | 백엔드 작업만 | 본인 읽음 처리 또는 백엔드 | 기본 금지 |

필수 검증:

- 사용자 A JWT로 사용자 B의 ID를 직접 지정해도 조회·수정 불가
- 목록, 상세, 통계, 최신 리포트가 모두 사용자 범위로 제한
- service role 작업은 대상 `user_id`를 명시하고 감사 로그를 남김

## 6. API와 Repository 변경 원칙

공개 endpoint 경로는 가능한 한 유지하고 인증 의미만 사용자 JWT 기반으로 전환합니다.

모든 repository 메서드는 암묵적인 전역 조회를 금지하고 다음 중 하나를 사용해야 합니다.

```text
repository.for_user(user_id)
method(..., user_id=user_id)
```

권장 방향은 요청 범위를 벗어나기 어려운 `repository.for_user(user_id)`입니다.

추가 설계 요구:

- FastAPI dependency에서 검증된 `CurrentUser` 제공
- 사용자 식별자는 요청 body 값을 신뢰하지 않고 JWT에서만 파생
- 사용자별 rate limit과 OpenAI 예산 한도 적용
- 관리자/스케줄러 endpoint는 사용자 API와 별도 권한 모델 사용
- 모든 사용자 데이터 접근에 구조화된 감사 이벤트 기록

## 7. 멀티유저 리포트 스케줄

현재 GitHub Actions는 국내/글로벌 endpoint를 한 번 호출하는 단일 사용자 구조입니다.
멀티유저에서는 한 요청 안에서 모든 사용자의 장시간 리포트를 생성하면 timeout과 비용 폭주
위험이 있습니다.

구현 전 선택이 필요한 구조:

### 권장안: Render paid worker + Supabase report_jobs

- GitHub Actions는 스케줄 시각에 dispatcher endpoint만 호출
- dispatcher는 대상 사용자별 `report_jobs`를 생성
- Render paid worker가 사용자별 job을 순차/제한 병렬 처리
- 사용자별 동시 실행 수와 OpenAI 예산을 강제
- 실패·재시도·알림은 사용자별 job에 기록

이 구조는 별도 worker 도입이므로 Phase 10 구현 승인과 `AGENTS.md` 개정이 필요합니다.
외부 queue provider는 현재 승인되지 않았으므로 사용하지 않습니다.

### 대안: GitHub Actions가 사용자별 endpoint 호출

사용자 목록과 토큰 관리가 GitHub Actions에 노출되고 사용자 수 증가에 취약하므로 권장하지
않습니다.

## 8. 비용·사용량 통제

상업화 전 사용자별 비용 상한이 필수입니다.

설계 대상:

- 사용자별 일/월 OpenAI 요청 수와 추정 비용 원장
- 리포트 유형별 모델·토큰 한도
- 한도 도달 시 technical-only fallback 또는 생성 거절 정책
- yfinance/pykrx/GDELT 실패율과 호출량 모니터링
- Render/Supabase paid tier 용량 경보

권장 신규 설계 테이블:

```text
usage_ledger
subscription_entitlements
audit_events
```

구체 스키마와 결제 제공자는 구현 승인 시 별도 확정합니다.

## 9. 법률·운영 게이트

상업화 전에 한국 투자자문 관련 법률 검토가 필요합니다. 이 문서는 법률 판단을 대신하지
않습니다.

검토 범위:

- 서비스가 투자자문업 또는 유사 규제 대상에 해당하는지
- 유료 추천·개인화 리포트의 허용 범위
- 성과 통계와 백테스트 표시 방식
- 면책 문구와 위험 고지
- 사용자 자산·투자 성향 데이터의 개인정보 처리
- 알림/Telegram 전송에 포함 가능한 정보 범위
- 데이터 보존·삭제·탈퇴 정책

법률 검토 결과가 현재 제품 경계와 충돌하면 구현보다 먼저 `AGENTS.md`를 개정합니다.

## 10. 단계적 출시 계획

### T0. 승인과 설계 확정

- 보안/비용/법률/스케줄 구조 결정
- 위협 모델과 데이터 분류 작성
- migration과 롤백 계획 검토

### T1. 내부 멀티유저 기반

- Supabase Auth, `user_id`, RLS
- 기존 데이터 소유자 backfill
- 사용자 범위 repository와 API 테스트
- 관리자 기능 없이 초대된 내부 계정만 허용

### T2. 사용자별 작업·비용 통제

- 사용자별 report_jobs 처리
- OpenAI 예산·rate limit·감사 로그
- 운영 대시보드와 장애 대응 절차

### T3. 제한 베타

- 법률 문서 반영
- 데이터 삭제/탈퇴/내보내기
- 보안 테스트와 소수 사용자 운영

### T4. 상업화 결정

- 결제 제공자 별도 승인
- 비용과 규제 리스크 재검토
- 명시적 출시 승인 후에만 진행

## 11. 테스트와 완료 기준

구현 승인 후 최소 완료 기준:

- 사용자 A/B 교차 접근 방지 API·RLS 테스트
- 모든 목록/상세/통계/알림의 사용자 격리 테스트
- 스케줄 job 중복·실패·재시도·예산 한도 테스트
- service role secret과 JWT 로그 노출 검사
- 기존 단일 사용자 데이터 이관 검증과 롤백 리허설
- 부하 테스트와 사용자별 비용 상한 검증
- 법률·개인정보·약관 검토 완료 기록
- 자동 매매/주문 실행 코드가 없음을 재검토

## 12. 미결정 사항

구현 전에 사용자가 결정해야 할 항목:

1. 로그인 방식과 계정 초대/가입 정책
2. 기존 데이터 소유자 계정
3. 멀티유저 스케줄 worker 도입 여부
4. 사용자별 OpenAI 월 예산과 초과 정책
5. 데이터 보존·탈퇴·삭제 정책
6. 무료/유료 기능 경계와 결제 제공자
7. 법률 검토 결과에 따른 서비스 범위

