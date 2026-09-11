# 로컬 원장 검증·잔고 대사 엔진

## 구현 범위

계좌별 기준일 잔고와 JSON/CSV 증거를 검증하고, 지정한 날짜의 현금·수량·미수금·미지급금을
재생한다. 관측 잔고와 비교해 차이를 반환한다. 외부 API, DB, 주문, 기존 대시보드에
연결하지 않은 로컬 도구다. 실제 계좌 수익률 및 실현손익은 항상 null이다.

핵심 구현:

- `backend/app/models/account_ledger.py`: Decimal 기반 이벤트·기초/관측 잔고 계약.
- `backend/app/services/ledger/validation.py`: 오류 행을 격리하는 입력 검증.
- `backend/app/services/ledger/io.py`: 공통 CSV 입력 형식.
- `backend/app/services/ledger/replay.py`: 계좌별 revision 대조와 잔고 재생.
- `backend/app/services/ledger/reconciliation.py`: 관측 잔고와 구성 요소별 잔차 계산.
- `scripts/replay_account_ledger.py`: 입력을 변경하지 않는 로컬 실행 명령.

## 실행

아래 파일은 실제 계좌가 아닌 가상 자료다. source_record_hash 역시 설명용 식별자다.

```powershell
backend/.venv/Scripts/python.exe scripts/replay_account_ledger.py `
  docs/examples/account_ledger_synthetic.json `
  --output ledger-result.json
```

출력 파일이 이미 있으면 덮어쓰지 않는다. 입력 파일과 CSV의 실제 SHA-256은 결과의
`input_hashes`에 기록한다. 입력 자료의 source_record_hash는 제공자가 주장한 원본 참조로,
실제 원본 문서의 진위나 해시 일치가 자동 인증된다는 뜻이 아니다.

CSV 사용 시 JSON에서 events를 비우거나 제거하고 `--events-csv events.csv`를 추가한다.
둘 다 제공하면 거부한다. UTF-8 CSV이며 열 이름은 LedgerEvent 필드명과 같다.
금액은 소수 문자열 그대로 사용하고, 선택 금액 필드의 빈 칸은 null이다.
settlement_confirmed는 `true`/`false`, revision은 정수로 입력한다.
CSV 행 폭이나 중복 열 이름이 잘못됐으면 거부한다. 특정 금융기관의 다운로드 서식
자동 인식 기능은 포함하지 않는다.

## 가상 예제 결과

기초 현금 USD 1,000·KRW 1,000,000에서 다음을 반영한다.

1. AAPL 2주, 거래금액 USD 200·수수료 USD 1 매수 및 결제 확인.
2. 배당 USD 10·세금 USD 1.5, 순입금 USD 8.5.
3. KRW 140,000과 수수료 KRW 100으로 USD 100 환전.

최종 현금은 USD 907.5·KRW 859,900, 주식은 AAPL 2주, 미수·미지급은 0이다.
가상 관측 잔고와 정확히 일치한다. 환전 금액은 외부 입금으로 집계하지 않는다.

## 입력·시간·결제 정책

기초와 관측 잔고는 KST 날짜 종료 기준이다. 두 통화의 현금·미수·미지급을 0도 생략하지
않고 명시해야 한다. positions는 `US:AAPL:USD`, `KR:005930:KRW` 형식의 수량 맵이다.
cash_basis는 settled만 허용한다. 가용 매수금액을 기초 정산 현금으로 받아들이지 않는다.

금액은 float 대신 소수 문자열로 입력하며 numeric(38,12) 범위를 초과하면 반올림하지
않고 격리한다. 계산은 Decimal 정밀도 60에서 수행한다. 빈 수수료와 수수료 0을 구분한다.

observed_at은 증거를 확인한 시각이며 timezone이 필요하다. known_at 이후의 정상 관측은
재생에 쓰지 않는다. 결과는 as_of 시점까지의 사건을 known_at까지 알려진 자료로 재구성한
것이다. 당시 알 수 있었던 성과를 재현하려면 known_at도 해당 시점으로 제한해야 한다.
정확한 effective_at은 KST로 변환한다. 날짜만 있고 원래 시간대가 KST가 아니면 계좌
날짜 경계를 추정하지 않고 격리한다. 잘못된 행이 있으면 결과를 incomplete로 남긴다.

거래는 거래일에 수량을 바꾸고, 결제가 확인되지 않았으면 현금을 그대로 두고 미수·
미지급을 반영한다. settlement_confirmed=true와 해당 결제일을 관측한 증거가 있고,
결제일이 as_of 이내인 경우만 현금으로 옮긴다. API의 결제 예정일만으로 true를 만들면
안 된다. 같은 거래를 결제 때 다시 수량 증가나 비용으로 반영하지 않는다.

## 중복·정정 정책

계좌+event_key별 revision 1부터 연속된 체인을 요구한다. 정정은 이전
source_record_hash를 supersedes_hash로 명시해야 한다. 입력 순서가 바뀌어도
체인에 따른 활성 금액은 같다. 관측시각만 다른 동일 revision은 경제적 중복으로 처리한다.

같은 revision의 상충 값, 끊긴 체인, 역전된 관측 시각은 해당 그룹을 격리한다. 잘못된
정정 행을 제외한 뒤 옛 revision으로 조용히 돌아가지 않는다. 같은 원본 행을 다른
event_key로 다시 입력하는 것도 차단한다. 다른 원본 행의 동일 금액 거래는 유지한다.

원본 증거와 정정 체인은 결과 evidence에 보존한다. 금액 분개는 이전 버전 취소 분개와
새 버전을 함께 기록한다. 명시적 reversal은 최종 영향만 취소하고 증거를 지우지 않는다.
기초 잔고 기준일을 가로지르는 정정은 기초 자료 자체의 재대사가 필요해 격리한다.

API execution_aggregate는 개별 거래로 기장하지 않는다. 누적 2→5주를 7주로
합산하지 않고, 미확정 상태와 원문을 남긴다. 명세서에서 같은 실제 거래가 중복된 경우
판별하려면 안정적인 source_key/event_key와 증거 연결이 필요하다. 서로 다른 문서의
경제적 중복까지 자동 인증하지 않는다.

## 회계 계산의 한계

통화별 금액 분개 합은 0이어야 한다. security_notional_clearing은 매매금액의 대응
계정으로, 잔여 취득원가나 실현손익이 아니다. 원가 방법·기초 취득원가를 아직 모델링하지
않았으므로 realized_profit_loss와 return_rate는 null이다.

주식 입출고는 수량을 반영하되 이전 자산의 평가액이 모델링되지 않았다는 사유를 남긴다.
기업행사는 검증된 수량 증감만 반영한다. 분할 비율을 자동 추론하거나 합병·단주대금을
만들지 않는다. 기초 미수·미지급은 잔액으로 유지하며, 그 항목의 후속 결제 일정을
자동 생성하지 않는다. 해당 내역이 움직이는 실제 자료를 처리하려면 추가 결제 증거
계약이 필요하다.

재생은 종료 잔고 대사용이며 장중 현금 부족·당일 거래 순서·세무 lot 계산을 검증하지
않는다. 종료 수량이나 잔고가 음수이면 incomplete로 표시한다. 대사 허용 오차는 0이며
양수/음수 잔차를 숨기지 않는다.

matched는 제공된 숫자가 일치한다는 뜻이다. 모든 거래·현금흐름이 빠짐없다는 뜻은
아니며 coverage_verified=False를 유지한다. 미확정·격리 사유가 있으면 숫자가 같아도
incomplete다. 다음 단계는 영속 저장소와 실제 명세서 형식 연결이다.

후속 구현: [비파괴 저장소와 공통 CSV 연결](account_ledger_storage_2026_09_11.md)이 추가됐다.
실제 명세서 확보와 운영 DB 적용은 별도로 남아 있다.

## 검증 결과

2026-09-11 전체 백엔드 pytest 676개 통과(기존 경고 3개), Ruff와 Black 검사 통과.
가상 예제 재생 및 대사 결과는 matched이며, 출력 파일 재사용 시 덮어쓰기를 거부한다.
실제 계좌·DB 검증이나 운영 배포는 이 작업에 포함하지 않았다.
