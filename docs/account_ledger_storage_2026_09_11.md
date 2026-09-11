# 비파괴 원장 저장소와 명세서 연결

2026-09-11 구현. 실제 거래명세서는 사용자가 아직 보유하지 않았다고 확인했다.
이번 결과는 일반 CSV 매핑·로컬 원본 보존·DB 저장 및 재생 연결이며, 실제 토스
명세서나 운영 계좌의 대사가 완료된 것은 아니다.

## 저장 구조

Migration 026은 기존 테이블과 데이터를 수정하지 않고 다음 8개 테이블만 추가한다.

| 테이블 | 보존 내용 |
|---|---|
| ledger_accounts | 독립 원장 계좌 키. 브로커 계좌 연결은 후속 단계 |
| ledger_import_runs | 문서·매핑 해시, 관측 시각, 입력 행 수 |
| ledger_source_records | 실제 문서·행 해시, 행 번호. 원문 payload는 저장하지 않음 |
| ledger_import_sources | 같은 계좌 내 수집 실행과 증거 행의 연결 |
| ledger_events | 검증된 이벤트의 모든 revision과 최초 관측 |
| ledger_import_results | 게시된 이벤트 목록과 검증 오류. 접수만 된 실행과 구분 |
| ledger_reconciliation_runs | 기초·관측 잔고, 입력 해시, 재생 결과와 잔차 |
| ledger_postings | 대사 실행별 통화·계정·금액 분개 |

모든 테이블은 RLS를 활성화하고 service_role에 SELECT/INSERT만 부여한다.
UPDATE/DELETE/TRUNCATE는 트리거로도 거절한다. 계좌를 포함한 복합 FK로 다른 계좌의
증거 연결을 막는다. assets FK가 없으므로 기존 보유 자산 삭제와 원장은 독립적이다.
토큰·로그인·공개 API 계약은 바꾸지 않는다.

원문 접수와 검증 이벤트 게시를 별도 RPC 트랜잭션으로 나눴다. 게시 도중 실패하면
이벤트와 게시 결과는 함께 rollback되고 접수 증거는 남는다. 같은 내용 재시도는 중복
저장하지 않는다. 같은 revision의 금액·품질·출처 변경은 충돌이며 명시적인 새 revision이
필요하다. 이후 시각의 동일 관측은 별도 수집 이력에 남기되 최초 이벤트는 유지한다.
최초 기록보다 이른 관측 시각은 자동 소급 적용하지 않고 거절한다.

금액 문자열은 원래 소수 자릿수를 유지한다. JSON에서도 `1E-12` 대신
`0.000000000001`처럼 직렬화한다. PostgreSQL 분개는 typmod 없는 numeric에
범위·scale 검사를 적용해 numeric(38,12)의 묵시적 반올림을 방지한다.
수량은 이벤트와 재생 결과에 보존하며 금액 분개 계정을 취득원가로 해석하지 않는다.

## CSV 연결

프로젝트 루트에서 가상 예제를 로컬로 검증한다.

```powershell
backend/.venv/Scripts/python.exe scripts/import_account_statement.py `
  docs/examples/account_statement_synthetic.csv `
  --mapping docs/examples/account_statement_mapping.json `
  --account-id synthetic-demo `
  --observed-at "2026-09-11T12:00:00+09:00"
```

기본 실행은 네트워크나 DB에 접근하지 않는다. 문서 SHA-256 아래에 original.csv,
원래 매핑 파일, 정규화 결과를 저장한다. 같은 파일은 내용이 같은지 확인하고 재사용하며
기존 내용을 덮어쓰지 않는다. 잘못된 CSV도 크기 제한 내에서는 검증 전에 원본부터
보존한다. 모든 보관 경로는 Git 제외된 backups 아래로 제한한다.

매핑 JSON은 `version: statement_csv_v1`, `columns`, `constants`, `value_maps`를
지원한다. 날짜는 YYYY-MM-DD, 금액은 소수 문자열, 참/거짓은 명시적인 값이어야 한다.
지역별 날짜 형식·천 단위 구분자·부호·비용 0을 추론하지 않는다. 열 이름과 거래유형
값 변환은 원본 서식을 확인하고 명시적으로 지정한다. 미매핑 메모 열은 DB로 보내지
않으며 행 해시 계산에는 포함한다.

기본 quality는 provisional이다. `validated`는 필드 계약이 맞다는 뜻이며, 원장 반영이나
투자성과 검증이 완료됐다는 뜻은 아니다. 명세서 증거를 확인한 경우에만 매핑에서
verified를 명시한다. 자료가 누락되면 0을 채우지 않는다.

실제 DB 저장은 migration 026이 적용된 환경에서 같은 명령에 `--persist`를 추가한다.
이 경우에만 backend/.env의 Supabase 설정을 읽는다. 파일을 다시 정규화해 원본과
매핑의 해시뿐 아니라 저장할 금액·행 대응까지 재검증한다.

선택적으로 `--context <JSON 경로>`를 함께 전달하면 저장된 계좌 전체 이벤트를 읽고
재생·대사를 새 실행으로 보존한다. JSON 필드는 기존 로컬 엔진과 같은 `opening`,
`as_of`, `known_at`, 선택적 `observed`다. 원문 context도 로컬에 보관한다.
계좌가 다른 context는 거절한다. 수집 저장과 대사 저장은 별도 단계이므로 대사가
실패해도 이미 보존한 증거를 삭제하지 않는다.

## 검증과 한계

전체 백엔드 테스트 719개 통과(기존 경고 3개), Ruff·Black 통과.
여기에는 실제 PostgreSQL 통합 테스트 4개가 포함된다. 최종 migration 파일은 새
로컬 DB에 다시 적용해 SQL 검증을 통과했고, 가상 CSV는 2개 이벤트·오류 0개로 검증됐다.

실제 운영 DB 대신 일회용 로컬 PostgreSQL 17.11에서 migration과 RPC를 실행했다.
동시 8회 입력, 재관측, 충돌 시 rollback, 교차 계좌 거절, 권한 차단, 숫자 정밀도 및
통화별 분개 균형을 확인했다. 모의 RPC 테스트와 실제 DB 테스트를 구분한다.
원문은 외부 분석 서비스로 보내지 않았다. DB 검증 도구는 PostgreSQL 공식 다운로드
페이지가 안내하는 EDB 바이너리를 로컬 검증용으로만 사용했다.

재현용 실제 DB 테스트는 disposable DB에 migration 026과 anon/authenticated,
service_role(BYPASSRLS) 역할을 준비한 뒤 `LEDGER_TEST_PSQL`에 psql 경로를 지정한다.
`backend/tests/db/test_ledger_postgres.py`는 운영 환경변수를 읽지 않고
127.0.0.1:55439 / postgres / ledger_test만 사용한다. 설정하지 않은 일반 CI에서는
이 통합 테스트를 건너뛰며, 나머지 단위 테스트는 그대로 실행한다.

남은 범위:

- 운영 Supabase에 migration 026 적용 및 운영 RPC 확인. 이번에는 적용하지 않았다.
- 실제 명세서 수령 후 서식·부호·정정·결제 표현을 검증하고 매핑 확정.
- XLSX/PDF와 토스 전용 어댑터, 주문 조회 수집은 미구현.
- 과거 partial/rejected 또는 게시 실패 이력은 보수적으로 대사를 incomplete로 만든다.
  성공 재시도는 같은 실행을 완결하지만, 다른 매핑으로 수정한 과거 오류를 해소하는
  명시적 검토 이력은 후속 작업이다. 임의로 오류를 숨기지 않는다.
- 문서 해시+행 번호는 동일 문서의 중복만 식별한다. 서로 다른 문서의 겹친 거래는
  검토가 필요하다. 원본·매핑 로컬 보관소의 백업도 별도로 유지해야 한다.
- 취득원가·기초 미결제 잔액의 후속 결제·평가·수익률은 후속 단계다.
  coverage_verified는 항상 false이며 수익률과 실현손익은 null이다.

## 이번 결정

원본 전체를 DB에 넣는 초안 대신 원문·매핑은 로컬에 보관하고 DB에는 허용된 필드와
해시만 저장했다. 개인정보가 포함된 임의 메모의 업로드를 막는 대신 원본 보관소를
별도로 백업해야 한다. 기존 보유 동기화와 원장을 연결하지 않아 과거 자료를 만들거나
현재 매수 가능액을 정산 현금으로 오인하지 않는다.

DB 함수는 [Supabase 공식 권한 안내](https://supabase.com/docs/guides/database/functions)의
security invoker·호출 권한 원칙을 적용했다. 새 실행마다 재생 결과를 보존하므로
기존 분개를 덮어쓰지 않고 결제·정정 전후를 비교할 수 있다.
