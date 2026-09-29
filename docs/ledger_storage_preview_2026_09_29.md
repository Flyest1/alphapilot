# 기존 운영 원장 연결과 저장 전 검토

2026-09-29 승인된 묶음 2의 조회·검토 단계다. 실제 명세서는 아직 제공되지 않았으므로
실제 자료 저장과 실계좌 대사 완료는 후속 단계다.

## 실행

기존 준비 목록을 작성하고 기존 원장과 같은 account_id를 사용한다.
실계좌 번호 대신 일관된 별칭을 사용한다.

```powershell
backend/.venv/Scripts/python.exe scripts/prepare_account_ledger.py preview `
  backups/ledger_preparation_20260923/manifest.json `
  --read-operating --expected-project-id ssfzsjzuemilbfiosmrp `
  --output-dir backups/ledger_operating_preview_20260929
```

입력 근거가 없거나 잘못됐으면 자격 증명을 읽지 않고 `not_checked` 보고서를 만든다.
원본·매핑·기간·잔고 근거가 유효하면 서버 환경변수로 선택 계좌의 거래·수집·검토 이력을
단일 GET RPC로 조회한다. 예상 프로젝트와 실제 HTTPS Supabase 주소가 다르면 호출 전에
중단한다. 이 명령은 DB에 저장하지 않는다.

내보낸 스냅샷을 재현할 때는 네트워크 없는 모드를 사용한다.

```powershell
backend/.venv/Scripts/python.exe scripts/prepare_account_ledger.py preview `
  backups/ledger_preparation_20260923/manifest.json `
  --snapshot backups/ledger_operating_preview_20260929/snapshot.json `
  --output-dir backups/ledger_offline_preview_20260929
```

출력은 Git 제외 `backups` 아래 새 폴더만 허용한다. 기존 출력은 덮어쓰지 않는다.
`report.json`, 한국어 `report.md`, 조회 근거 `snapshot.json`은 비공개 로컬 자료다.
스냅샷에는 계좌 별칭·정규화 거래·검토 이력이 포함되고 암호화되지 않는다.
콘솔에는 상태·차단 개수만 출력한다. 원본 CSV·메모·키·예외 전문은 출력하지 않는다.

## 검토 결과

- 정확히 같은 수집은 `already_imported`로 처리해 중복 반영하지 않는다.
- 나중 재관측은 최초 이벤트를 보존한다. 같은 버전 내용 충돌·더 이른 관측은 차단한다.
- 정정은 기존 버전과 원본 해시 연결을 검증한다. 이전 버전 누락·잘못된 연결은 차단한다.
- 다른 문서의 동일한 경제적 거래는 중복 후보다. 기존 명시적 검토만 반영한다.
- 미완료 수집, 검토 모순, 미확인 증거, 잔고 차이는 차단한다.
- 새 자료만의 대사가 불완전해도 자료 형식과 증거가 유효하면 기존 원장과 합산해 재판정한다.
  원래 판정은 `local_status`, `local_projection_blockers`에 보존한다.
- 계좌·거래·수집 식별 해시와 게시 자료의 일관성을 검증한다.
  조회 실패를 빈 원장이나 샘플로 대체하지 않는다.

합산 잔고 차이 = 제공된 기말 정산 잔고 − 기존 원장과 새 자료의 계산 잔고.
가용 매수금액은 정산 잔고로 사용하지 않는다. 허용 오차는 0이다.
스냅샷은 거래/수집/검토 목록 각각 최대 10,000개, 새 문서 최대 24개,
합산 거래 최대 10,000개다. 오프라인 스냅샷 파일은 최대 5 MiB다.

`ready_for_review`는 검토 가능 상태다. 전체 거래 완전성, 자료 진실성, 실제 수익률,
실현손익 또는 저장 승인을 뜻하지 않는다. `coverage_verified=false`를 유지한다.
조회 후 원장이 바뀔 수 있으므로 실제 import 직전에 새로 조회하고 해시·차단 사유를
검토해야 한다. 기존 저장 RPC의 원자성·불변성 검사는 저장 시 그대로 작동한다.
이 보고서는 저장 권한 토큰으로 사용하지 않는다.

종료 코드: 0=검토 가능, 2=보고서 생성·차단, 1=입출력 실패.
실제 명세서 확보 후 새 조회 → 원문 및 중복/정정 검토 → 명시적 import → 저장 후 대사 순서다.
새 DB 스키마·브로커 호출·자동 주문 경로는 추가하지 않는다.

GET RPC는 [Supabase Python 공식 문서](https://supabase.com/docs/reference/python/rpc)의
읽기 전용 함수 호출 방식으로 구현한다. 운영 함수는 migration 027의 STABLE SELECT 함수다.

## 검증 기록

2026-09-29 최종 로컬 검사: 백엔드 전체 816 passed, 1 skipped(Windows 링크 생성 권한),
기존 경고 3개. 실제 로컬 PostgreSQL의 원장 검증 8개와 접근 권한 검증 23개를 포함한다.
Ruff·Black·diff 공백 검사 통과. 새 미리보기/CLI 회귀 검증은 20개다.
정확한 재수집, 최초 관측 보존, 충돌, 정정 연결, 기존 중복 검토 반영, 합산 잔고,
입력 부족 시 조회 차단, 잘못된 프로젝트, 조회 실패와 오프라인 재현을 확인했다.

운영 Supabase의 빈 검증 계좌에 GET RPC 1회로 빈 스냅샷 응답을 확인했다.
실계좌 거래·잔고를 이용한 검증은 아니며 DB 저장은 없었다.
기존 비공개 준비 폴더의 자료 부족 보고서는
`backups/ledger_operating_preview_20260929/report.md`에 보존했다.
12개 보완 항목으로 조회 전에 차단됐고 Git 제외를 확인했다.
