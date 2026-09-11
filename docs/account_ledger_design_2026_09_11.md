# 실제 계좌 성과 원장 설계

상태: 로컬 입력 검증·잔고 재생·대사 구현 완료. [실행과 제한](local_account_ledger_2026_09_11.md).
DB 마이그레이션·실계좌 수집·수익률 계산은 구현 전.
근거: [Toss 조회 범위 조사](toss_ledger_capabilities_2026_09_11.md).

## 목표와 경계

실제 계좌의 수량·현금 변화를 재현하고, 자금 유입을 투자수익과 분리한다. API가
제공하지 않는 자료는 명세서로 보완한다. 빈 자료를 0으로 채워 수익률을 만들지 않는다.
초기 단계는 단일 사용자·현물·KRW/USD 범위다. 기존 보고서·추천·보유 동기화는 유지한다.
이 원장은 주문을 내지 않으며 주문 실행 서비스의 원장과도 책임을 구분한다.

## 증거 → 관측 → 분개 → 대사 → 성과

증거 수집과 회계 반영을 분리한다. 원본을 받았다고 자동으로 확정 분개하지 않는다.

| 저장 대상(신규 additive 테이블 초안) | 주요 필드와 역할 |
|---|---|
| `ledger_accounts` | id, provider, external_account_id, base_currency, inception_date(nullable). 공급자+외부 계좌 식별자 유일 |
| `ledger_import_runs` | id, account_id, source_type, requested_from/to, observed_from/to, status, cursor, schema_version, started_at/completed_at. 수집 완주와 조회 범위를 구분 |
| `ledger_source_records` | id, account_id, source_type, source_key, payload_hash, payload, observed_at, import_run_id. 계좌+출처+키+해시 유일; 원본 개정본 append-only |
| `ledger_events` | id, account_id, event_key, revision, type, symbol, currency, effective_at, settlement_date, evidence_id, precision, quality, supersedes_id. 미확인 상태는 posting 불가 |
| `ledger_postings` | id, event_id, leg, book_account, currency, amount, symbol, quantity. 이벤트+leg 유일, 원장 분개와 보유 수량 기록 |
| `ledger_reconciliation_runs` | id, account_id, as_of, input_hashes, opening_basis, residuals, coverage, status. 불일치와 제외 사유 보존 |
| `ledger_valuations` | id, account_id, as_of, revision, positions, cash, receivables/payables, price/FX lineage, completeness, net_value(nullable). 성과 계산 입력 |

실제 DDL은 구현 작업에서 고정한다. account_id는 원장 내부 계좌 키이며 user_id가 아니다.
외부 accountSeq는 서버 쪽 식별 정보로 취급하고 토큰·클라이언트 시크릿·Authorization
헤더는 원본 payload에도 저장하지 않는다. 읽기는 기존 사용자 토큰, 쓰기는 서버를 통해서만
허용하고 신규 테이블은 service_role 외 직접 접근을 허용하지 않는다.

금액·수량은 Python Decimal과 PostgreSQL numeric을 사용한다. 원본 decimal 문자열은
보존하며 숫자형 변환 과정에서 float를 사용하지 않는다. 최초 후보는 numeric(38,12)지만
정밀도 초과 입력은 반올림 저장하지 않고 검토 대상으로 남긴다. 통화별 허용 반올림과
허용 대사 오차는 금액 규모로 확대하지 않으며 별도 버전의 정책으로 정한다.

assets 삭제가 원장 삭제로 이어지지 않게 한다. 종목·계좌 식별을 자체 보존하고 필요하면
asset_id는 nullable 참조만 둔다. 기존 snapshots와 추천 성과는 수정하거나 이관하지 않는다.

## 입력 계약 초안

원장 입력 공통 필드:

```text
account_id, source_type(api|statement|manual), source_key, source_record_hash
event_type, event_date, effective_at(nullable), timezone
symbol(nullable), currency, quantity(decimal string|null)
gross_amount(decimal string|null), fee(decimal string|null), tax(decimal string|null)
net_cash_amount(decimal string|null), settlement_date(nullable)
counter_currency(nullable), counter_amount(decimal string|null)
precision(exact_time|date_only|aggregate), quality(verified|provisional|quarantined)
```

지원 이벤트: opening_balance, execution_aggregate, trade, deposit, withdrawal,
dividend, interest, fx_conversion, security_transfer, corporate_action, reversal.
이벤트별 필수 항목을 별도 검증한다. 수수료·세금이 별도 입출금 행으로 제공되는 경우
원래 거래의 비용 leg와 중복되지 않게 연결하고, 연결을 확인할 수 없으면 격리한다.

거래명세서 원본 형식은 아직 확보하지 않았다. 특정 CSV/XLSX 형식을 지원한다고 가정하지
않고 먼저 위 공통 JSON/CSV 계약과 가상 fixture로 검증한다. 원본 서식 확보 후 해당
서식 전용 어댑터를 붙인다. 현재 자산 CSV 가져오기와는 별도 기능이다.

## 중복·부분 체결·정정 처리

- API의 계좌+orderId는 관측 식별 키다. 동일 payload 재수집은 같은 증거로 참조하고
  금액을 다시 더하지 않는다. 다른 payload는 새 revision으로 보존한다.
- 누적 수량 2→5, 금액 200→510은 두 건의 200+510 거래가 아니다. API 누계는
  `execution_aggregate`로 보존하고, 상세 체결 증거 없이는 체결시각·개별 체결가를 생성하지 않는다.
- 여러 날 체결된 누계를 마지막 체결일에 몰아 넣으면 일별 성과가 왜곡된다. 명세서로
  날짜별 체결을 분리할 수 있을 때만 일별 확정 분개한다. 그전에는 해당 구간 성과를 제한한다.
- null 수수료는 0 수수료가 아니다. 상태가 종료돼도 비용·결제·대체 주문 연결 검증이
  끝나지 않으면 미확정으로 둔다. 정정 주문의 중복 체결 합산을 잔고 대사로 탐지한다.
- 수정은 기존 원문과 분개를 지우지 않고 취소 분개+새 revision으로 기록한다. 재생 결과는
  활성 revision 하나만 반영한다. out-of-order 응답을 최신 자료로 자동 채택하지 않는다.
- 명세서 행 ID가 없으면 문서 해시+행 번호는 수집 중복 방지에만 사용한다. 내용이 같은
  두 실제 거래를 합치지 않는다. 서로 다른 문서의 중복 기간은 금액·수량·시간·원본 참조로
  조정하며 모호하면 사용자 검토 대상으로 둔다.

## 회계와 잔고 대사

분개는 통화별 차변·대변 금액이 균형을 이뤄야 한다. 수량은 금액과 별도로 검증한다.
매수는 증권 원가/거래 미지급금, 매도는 거래 미수금/증권 원가 및 실현손익으로 기록하고
결제 시 미수·미지급을 현금으로 이동한다. 거래일과 결제일을 모두 기록하여 결제 때 손익을
두 번 만들지 않는다. 정확한 취득 원가가 없으면 실현손익은 미확인으로 둔다.

배당은 세전 수입·원천징수·실입금 관계를 대조한다. 환전은 KRW/USD 두 leg를 같은
이벤트로 연결한다. 환전은 외부 입출금이 아니며, 통화별 clearing 분개와 실제 금액·
적용 환율·별도 비용을 함께 보존한다. 서로 다른 통화의 숫자를 그대로 합산하지 않는다.

계좌별 검증식:

```text
기초 수량 + 매수 - 매도 ± 입출고 ± 기업행사 = 관측 기말 수량
기초 정산 현금 + 확정 입출금 + 결제 현금 ± 환전 + 배당/이자 - 별도 비용 = 관측 정산 현금
총자산 = 주식 평가액 + 정산 현금 + 미수금 - 미지급금
```

기초 상태는 기준일 명세서의 수량·정산 현금·미수/미지급과 가격 근거로 확정한다.
현재 매입단가나 가용 매수금액으로 이전 계좌 상태를 추정하지 않는다. 기준일 이후
성과만 계산할 수 있어도 허용하며, 계좌 개설 이후 전체 성과라고 부르지 않는다.

증권 입출고는 수량 변화와 함께 계좌 범위의 외부 자금 이동이다. 시장가치·통화·평가
시점이 없으면 그 구간 수익률을 확정하지 않는다. 여러 계좌 통합 관점에서 내부 이체인지
외부 이체인지는 계좌 범위별로 명시하고 두 계좌의 대응 증거를 대조한다.

## 성과 계산과 공개 조건

완전성은 하나의 bool 대신 계좌/기간별로 `trades`, `cash_flows`, `fees_taxes`,
`corporate_actions`, `opening_state`, `valuations`, `fx`, `reconciliation`을 기록한다.
API 페이지 완료는 trades 완전성을 보증하지 않는다. 비지원 주문 유형 누락을 별도 표시한다.

1. 금액 손익은 같은 통화 기준 `기말 순자산 - 기초 순자산 - 순외부유입`이다. 환전은
   순외부유입에 포함하지 않는다. 원장 대사와 평가 완전성 검사를 먼저 통과해야 한다.
2. 정확한 TWR은 외부 현금흐름 전후 평가액이 있을 때 구간 수익률을 연결해 계산한다.
   현재 보고서 시점 snapshots만으로 정확한 TWR을 제공하지 않는다.
3. 평가 시점이 부족하지만 흐름 시각과 양 끝 평가가 확인되면 Modified Dietz를 근사치로
   제공할 수 있다: `(V1 - V0 - ΣCF)/(V0 + Σw·CF)`, w는 유입 후 남은 기간 비율이다.
   분모가 0 이하이거나 시각·흐름·평가가 누락되면 null과 이유를 반환한다.
4. 자금가중 수익률(XIRR)은 초기 범위에서 보류한다. 다중해·무해와 불완전 현금흐름의
   오해를 줄이기 위해, TWR/근사치와 대사 기반이 검증된 후 추가한다.
5. 가격·환율·배당·비용 기여를 분리하되 가격×환율 교차 효과와 미설명 잔차도 남긴다.
   잔차를 알파로 부르거나 임의로 가격 기여에 배분하지 않는다. 최초 버전은 금액 기여를
   먼저 제공하고 복수 기간 수익률 기여의 연결은 별도 검증한다.

예: 기초 100, 추가 입금 10, 기말 110이면 금액 손익은 0이다. 평가액 10 증가를
10% 투자수익으로 표시하면 안 된다. 현금 이동이 없는 기초 100→기말 105는 5%이며,
순수 환전은 통화별 잔고 이동이지 납입금 증가가 아니다.

결측 시 API 초안은 `status=insufficient_data`, `return_rate=null`, `missing_requirements`
와 평가 가능 기간을 반환한다. 현재 대시보드 지표는 새 원장이 준비됐다는 이유만으로
교체하지 않는다. 별도 계좌 성과 화면에서 출처·완전성·방법부터 공개한다.

## 배포 순서

1. 로컬 공통 입력 검증·원장 재생·대사 계산기와 fixture 테스트.
2. additive 저장소 및 원본 보존. 실제 명세서 형식은 확보 후 어댑터 추가.
3. 읽기 전용 API 주문 관측 수집과 기존 토큰 발급의 조율. 생산 토큰 재발급의 영향을 검증.
4. 기준일 자료로 수량·현금·비용 대사. 차이 해결 전 성과 공개 보류.
5. 계좌 성과 API·UI, 충분한 자료의 기간부터 제공.

미확인 자료가 필요해지는 시점에 정확한 항목만 요청한다. 지금은 설계와 fixture 기반
구현을 진행할 수 있어 추가 승인이나 계좌자료 제출을 요구하지 않는다. 실제 주문과
자금 사용은 이 계획의 범위에 없다.
