# 원장 오류 복구·완전성 관리

기존 원본·수집·이벤트를 보존하면서 검토 결정으로 재생 대상을 조정한다.
실제 명세서는 아직 없어 검증 예시는 모두 가상 자료다.

## 오류 해결

Migration 027은 ledger_reviews와 service_role 전용 RPC를 추가한다. 검토 revision과
서버 시각을 기록하며 수정·삭제·초기화를 차단한다. 같은 원문·행 수를 모두 검증한
대체 수집으로 오류를 해결한다. 원래 오류는 남고 reopen 이력으로 다시 불완전 상태로
돌릴 수 있다. 다른 문서를 오류 해결 근거로 자동 채택하지 않는다.

최초 expected_revision은 0, 다음 결정은 현재 revision을 전달한다. 동일 요청의
재시도는 같은 결정을 반환하며 다른 검토자가 먼저 변경했다면 충돌로 거절한다.
known_at 이후 결정은 과거 재생에 반영하지 않는다. 대체 수집의 유효 이벤트와
정정에 필요한 이전 revision을 유지하고, 잘못 매핑한 별도 키는 재생에서 제외한다.

## 문서 간 중복

다른 문서에서 금융 필드가 같은 거래를 후보로 표시한다. 10과 10.00은 같게 비교하지만
원문 문자열을 바꾸지 않는다. 같은 문서의 같은 금액 두 행을 자동 중복 처리하지 않는다.

- duplicate: 같은 거래로 확인. 중복 그룹에서 이벤트 키가 가장 작은 기록만 재생한다.
- distinct: 별개 거래로 확인. 모두 재생한다.
- reopen: 다시 미검토 상태로 둔다.

원본 이벤트는 모두 유지한다. 결정은 지정한 개정에만 적용되어 정정 후에는 다시 검토한다.
과거 기준시점의 예전 개정도 검토할 수 있다. 중복·별개 결정이 모순되면 해당 그룹을
제외하지 않고 불완전으로 표시한다. 후보 10,000쌍 초과 시 자동 제외를 중단한다.
거래일·비용 등 금융 내용이 다른 거래를 동일 거래로 추정하지 않는다.
검토로 quality를 승격하지 않으며 coverage_verified=false와 수익률=null을 유지한다.

## 검토 CLI

backend/.env의 서버 자격 증명으로 DB를 조회한다. 출력은 backups 아래 새 파일에만
저장한다. 다음 demo는 원장 내부 계좌 키 예시다.

```powershell
backend/.venv/Scripts/python.exe scripts/review_account_ledger.py inspect `
  --account-id demo --opening-date 2026-08-31 --as-of 2026-09-22 `
  --known-at "2026-09-23T09:00:00+09:00" --output backups/review-demo.json
```

출력에는 수집 상태·문서 해시·오류, 중복 후보의 키·revision, 현재 검토 이력이 포함된다.
수집 해결 요청 JSON은 다음 형태다. 자리표시자에는 실제 출력의 해시를 넣는다.

```json
{
  "kind": "import_resolution",
  "source_run_key": "오류 수집 해시",
  "replacement_run_key": "같은 원문을 검증한 대체 수집 해시",
  "decision": "resolve",
  "reason_code": "corrected_mapping"
}
```

재검토는 replacement_run_key=null, decision=reopen, reason_code=review_reopened다.
같은 가져오기 실행의 단순 실패는 원래 명령 재시도로 완결할 수 있어 별도 검토가 불필요하다.

중복 요청은 kind=duplicate_review, left_event_key/left_revision,
right_event_key/right_revision과 decision/reason_code를 넣는다. 후보의 키 순서를 따른다.
사유는 duplicate→same_transaction, distinct→separate_transactions,
reopen→review_reopened다.

```powershell
backend/.venv/Scripts/python.exe scripts/review_account_ledger.py record `
  --account-id demo --request backups/review-request.json --expected-revision 0
```

결정 후 가져오기 CLI의 --persist --context로 재생·대사를 새 실행으로 저장한다.
과거 대사는 변경하지 않는다. 검토는 실제 증거 확인을 대신하지 않는다.

## 원본 백업·복원

```powershell
backend/.venv/Scripts/python.exe scripts/backup_ledger_archive.py backup `
  backups/ledger_statements --output backups/ledger-backup.zip
backend/.venv/Scripts/python.exe scripts/backup_ledger_archive.py verify backups/ledger-backup.zip
backend/.venv/Scripts/python.exe scripts/backup_ledger_archive.py restore `
  backups/ledger-backup.zip --destination backups/ledger-restored
```

원본 CSV·정확한 매핑·정규화 결과·잔고 context와 파일 해시를 보존한다.
알 수 없는 파일, 중복 ZIP 경로, 경로 이탈, 링크, 해시 불일치를 거절한다.
전체 검증 후 새 경로를 독점 생성하여 복사하며 기존 파일·디렉터리를 덮어쓰지 않는다.
복사 실패 시 부분 복원 경로는 보존하므로 재시도는 다른 새 경로를 사용한다.

제한: 원본 CSV 5 MiB, 기타 파일 32 MiB, 총 자료 256 MiB, 5,000개 파일.
백업은 암호화되지 않으며 외부 업로드·자동 실행은 하지 않는다. DB 전체 백업이
아니므로 DB의 이벤트·검토 이력과 Supabase 백업은 별도로 관리한다.

## 검증·운영 기록

로컬 PostgreSQL에서 해결·재검토·중복 반영·동시 충돌·권한·원본 불변성을 검증했다.
가상 보관소 3개 파일 4,324바이트를 백업·검증·복원한 manifest SHA-256이 일치했다.
전체 테스트와 운영 배포 결과는 완료 후 아래에 기록한다.

로컬 전체 검증: 752 passed, 1 skipped, 기존 경고 3개. Windows 링크 생성 권한에
따른 1개 생략이며 ZIP 링크 거절은 검증됐다. Ruff·Black 통과. 새 PostgreSQL DB에
최종 026/027 파일을 순서대로 적용한 뒤 저장소·검토 SQL 검증을 다시 통과했다.

운영 사전 보안 점검에서 기존 public 테이블 20개의 RLS 비활성 및 anon SELECT 권한,
기존 함수 4개의 mutable search_path 경고가 확인됐다. 이번 원장에는 동일한 권한을
부여하지 않는다. 기존 영역의 익명 접근 차단은 우선순위 높은 별도 보안 작업이다.
[Supabase RLS 점검 안내](https://supabase.com/docs/guides/database/database-linter?lint=0013_rls_disabled_in_public).
