# 계좌 성과 원장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실제 계좌 증거의 중복 없는 보존·대사를 구현하고 자료가 완전한 기간에만 성과를 계산한다.

**Architecture:** 원본 관측, 정규화 이벤트, 분개, 대사, 평가를 분리한다. 로컬 순수 계산기를
먼저 검증하고 저장소와 읽기 전용 API를 뒤에 연결한다. 기존 추천 성과와 병행한다.

**Tech Stack:** 기존 Python 3.10, Decimal, Pydantic v2, FastAPI, Supabase, pytest.

**Spec:** `docs/account_ledger_design_2026_09_11.md`, `docs/toss_ledger_capabilities_2026_09_11.md`.

## 공통 조건

금액 float 사용 금지. 과거 데이터 소급 생성 금지. 운영 주문 경로 없음. 기존 자산·보고서
삭제 없음. 증거 없는 수익률은 null. 각 코드 커밋 전 전체 pytest·Ruff·Black 통과,
프론트엔드 변경 시 lint/test/build 추가. 실 DB 마이그레이션은 검토된 additive 변경만 적용.

## 작업 1: 로컬 입력 계약과 검증기

파일: `backend/app/models/account_ledger.py`, `backend/app/services/ledger/validation.py`,
`backend/tests/services/test_ledger_validation.py`.

입력: 공통 증거 JSON/CSV. 출력: 검증된 이벤트 또는 필드별 오류 목록. CLI용이며
아직 공개 API나 DB에 연결하지 않는다.

- [x] 숫자 문자열·통화·일시·출처 해시 검증의 실패 테스트 작성.
- [x] null 비용과 0 비용, 날짜만 있는 증거와 정확한 시각, 정밀도 초과를 구분.
- [x] 같은 문서 재입력과 동일 내용의 서로 다른 실제 거래를 구분하는 fixture 추가.
- [x] 모델·검증기를 구현하고 전체 검사 후 `feat: validate account ledger evidence` 커밋.

## 작업 2: 순수 원장 재생과 대사

파일: `backend/app/services/ledger/replay.py`, `reconciliation.py`,
`backend/tests/services/test_ledger_replay.py`, `test_ledger_reconciliation.py`.

입력: 작업 1의 검증 이벤트, 기초 상태, 관측 잔고. 출력: 통화별 원장·잔차·완전성.

- [x] 누적 체결 2→5 재조회가 총 7주가 되지 않는 테스트 작성.
- [x] 수정·취소 분개, 잘못된 정정 자료, 수수료 null의 격리 테스트 작성.
- [x] 매매일/결제일 구분과 환전 양 leg, 배당 세전/세금/실입금 대사 구현.
- [x] 기초 원가 없을 때 실현손익 null을 검증하고, 현금 입력 계약을 settled로 제한.
- [x] 전체 검사 후 `feat: replay and reconcile account ledger evidence` 커밋.

## 작업 3: 비파괴 저장소

파일: `backend/app/db/migrations/`의 다음 번호 migration,
`backend/app/db/ledger_repository.py`, `backend/tests/services/test_ledger_repository.py`.

입력: 증거/이벤트/분개. 출력: 중복 없는 영속 기록과 재생 가능한 revision.

- [ ] 설계 문서의 테이블·키·정밀도·접근 정책을 DDL로 고정하고 AGENTS.md에 반영.
- [ ] 동일 이벤트 동시 입력, 중간 실패 rollback, 다른 계좌 충돌 방지 테스트 작성.
- [ ] 원본 저장과 검증 이벤트 게시를 트랜잭션으로 분리하고 부분 수집 상태 보존.
- [ ] 기존 assets 삭제가 원장을 지우지 않는 테스트 후 scoped commit.

## 작업 4: 읽기 전용 주문 수집

파일: `backend/app/services/ledger/toss_reader.py`, 기존 Toss 인증 부분,
`backend/tests/services/test_toss_ledger_reader.py`.

입력: 명시적 계좌·주문 생성일 범위. 출력: 원문 페이지·주문 관측 및 coverage.

- [ ] HTTP mock으로 GET orders/detail 외 계좌 변경 요청을 금지하는 테스트 작성.
- [ ] CLOSED 커서 반복·빈 중간 페이지·429·계좌 불일치·알 수 없는 상태를 검증.
- [ ] OPEN 누계·기존 진행 주문 상세 재조회·겹치는 기간 및 정정 처리 구현.
- [ ] 기존 보유 동기화와 토큰 발급 경쟁을 조율하고 토큰/헤더 저장 금지 검증.
- [ ] 실제 계좌 요청은 제한된 조회로 먼저 확인. 최과거일을 보존 기간 보증으로 해석하지 않음.
- [ ] 전체 검사 후 scoped commit. 주문 생성/취소 기능은 포함하지 않음.

## 작업 5: 성과 계산과 별도 조회 화면

파일: `backend/app/services/ledger/performance.py`, `backend/app/routers/account_performance.py`,
`backend/tests/services/test_account_performance.py`; 프론트엔드 파일은 별도 UI 설계 후 확정.

- [ ] 외부 입금만 있는 기간의 손익 0, 비용 차감, 환전 내부 이동 테스트 작성.
- [ ] 자료 완전성 gate, 정확한 TWR/Modified Dietz 구분, 비양수 분모 null 구현.
- [ ] 가격·환율 교차 효과·배당·비용·잔차 합이 금액 손익과 일치하는 테스트 작성.
- [ ] 부분 자료·근사 성과의 표시를 검증하고 기존 대시보드 지표와 병행.
- [ ] 실제 기준일 명세서와 잔고 대사가 끝난 기간부터 공개하고 전체 검사 후 scoped commit.

2026-09-11 실행 결과: 작업 1~2의 로컬 입력 검증·재생·대사 엔진을 구현했다.
대사 테스트는 별도 파일 대신 `test_ledger_replay.py`에 통합했다. JSON/CSV CLI와
명시적인 가상 fixture로 검증했으며 전체 백엔드 테스트 676개가 통과했다.
브로커 주문 대체 관계의 실제 자료 검증은 작업 4에서 수행한다. 현재 엔진은 명시적인
revision 연결만 처리한다. 작업 3~5, 실제 명세서 검증과 기초 미결제 잔액의 후속 결제
계약은 남아 있다. 상세 범위는 `docs/local_account_ledger_2026_09_11.md`를 참조한다.
