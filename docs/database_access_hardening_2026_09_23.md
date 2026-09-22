# 기존 DB 익명 접근 차단

사용자가 2026-09-23 다음 우선 조치의 구현·푸시·배포를 승인했다.
운영 사전 점검에서 기존 public 테이블 20개의 RLS가 비활성이며 anon과 authenticated에
읽기·쓰기 권한이 있음을 확인했다. 이는 접근 가능한 권한 설정의 확인이며 실제 유출을
확인했다는 의미는 아니다. 프론트엔드는 FastAPI만 호출하고, 백엔드 저장소는
`SUPABASE_SERVICE_ROLE_KEY`로 DB에 접속한다.

## 결정과 범위

- migration 028은 기존 20개 테이블의 RLS를 활성화하고 public 테이블·시퀀스의
  PUBLIC/anon/authenticated 권한을 회수한다. 허용 정책을 만들지 않는 의도적 기본 차단이다.
- 기존 서버의 SELECT/INSERT/UPDATE/DELETE를 유지한다. 원장 9개 테이블의 서버 권한은
  SELECT/INSERT로 유지하며 수정·삭제·TRUNCATE 차단 트리거를 변경하지 않는다.
- 기존 신호 검증 트리거 함수 4개의 공개 실행 권한을 회수하고 search_path를
  `pg_catalog, public, pg_temp`로 고정한다. 임시 테이블로 검증 대상을 바꿀 수 없게 한다.
- 앱 migration 소유자인 postgres의 public 테이블·시퀀스·함수 자동 클라이언트 권한을
  제거한다. 함수의 암묵적 PUBLIC EXECUTE는 전역 기본 권한이므로 postgres가 향후
  생성하는 다른 스키마의 함수도 명시적 실행 권한이 필요하다. 기존 함수 권한은 별개다.
- Supabase 관리 역할 `supabase_admin`의 기본 권한 및 auth/storage 객체는 변경하지 않는다.
  다른 소유자로 추가하는 객체는 별도 권한 검토가 필요하다. 향후 앱 테이블에도 RLS를
  명시적으로 활성화하고 필요한 서버 권한만 부여해야 한다.
- 로그인, Auth, user_id, API 계약, 매매 정책은 변경하지 않는다. 새 외부 서비스나 유료
  비용을 추가하지 않는다. CI는 기존 GitHub Actions의 일회용 PostgreSQL 서비스로 검증한다.

## 검증 방법

`backend/tests/db/test_database_access_postgres.py`는 실제 PostgreSQL의 새 테스트 DB에
001~027 전체 migration과 가상 자산을 준비하고 028을 두 번 적용한다. 모든 테이블의
행 해시가 동일한지, 익명·authenticated 접근이 차단되는지, 서버 CRUD·토스 대사 RPC·
신호 검증·원장 조회가 동작하는지, 미래 객체의 기본 권한이 닫혀 있는지 검증한다.
SELECT가 실수로 다시 부여되어도 RLS가 행을 숨기는지도 확인한다.

고정 테스트 접속 대상은 `127.0.0.1:55439`, 사용자 `ledger_test`다. 앱 환경 파일이나
운영 키를 읽지 않는다. DB 이름은 `alphapilot_access_test_<uuid>`이며 로컬에는 점검을
위해 남긴다. CI 컨테이너는 작업 종료 시 폐기된다. 다른 포트·계정으로 우회하지 않는다.

```powershell
$env:DATABASE_ACCESS_TEST_PSQL = (Resolve-Path backups/ledger_schema_work/runtime/pgsql/bin/psql.exe).Path
backend/.venv/Scripts/python.exe -m pytest backend/tests/db/test_database_access_postgres.py -v
```

CI에서도 이 테스트를 실제 PostgreSQL 17로 실행한다. 별도의 원장 통합 테스트는 기존
`LEDGER_TEST_PSQL` 설정을 사용한다. 가상 데이터 검증은 실제 명세서 검증이나 토스 실계좌
동기화를 의미하지 않는다.

## 운영 적용과 복구

028은 트랜잭션으로 실행하고 lock_timeout 5초·statement_timeout 60초를 적용한다.
잠금 충돌이나 오류 시 전체 변경을 취소하고 원인을 확인한다. 데이터 DML은 포함하지 않는다.
Supabase CLI로 migration을 생성한 후 저장소의 순번 규칙에 맞춰
`backend/app/db/migrations/028_restrict_public_database_access.sql`로 보관했다.

배포 순서는 전체 테스트 → CI → 운영 migration → main 병합 및 Oracle 배포 →
실제 REST 익명 거절/서버 조회 및 advisor 확인이다. 서버 코드를 되돌려도 이번 DB 권한은
이전 service_role 접근 방식과 호환된다. 장애 시 누락된 서버 권한을 특정해 복원한다.
익명 접근 재개나 RLS 전체 해제를 자동 롤백으로 사용하지 않는다.

참고: [Supabase Data API 보안 지침](https://supabase.com/docs/guides/api/securing-your-api).
service_role 전용 테이블의 RLS no-policy INFO는 의도한 설계다.

로컬 검증: 전체 백엔드 775 passed, 1 skipped(Windows 링크 생성 권한), 기존 경고 3개.
새 PostgreSQL 접근 검증 23개와 기존 원장 DB 검증 8개를 포함한다. Ruff·Black 통과.
운영 적용 결과는 완료 후 아래에 기록한다.
