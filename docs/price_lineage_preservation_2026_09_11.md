# 신규 가격 증거 보존

## 변경

새로 조회한 주가에 `price_lineage_v1` 메타데이터를 붙인다. 기존 `market_data_cache.payload`,
`reports.report_inputs`와 `recommendation_cycles.metadata` JSON 공간을 사용하므로 DB
마이그레이션은 필요 없다. ReportContent와 기존 OHLCV 분석 열은 바꾸지 않는다.

보존 항목:

- 공급자·설치 패키지 버전·공급자 티커·UTC 수집 시각.
- pykrx `adjusted=True`, yfinance `auto_adjust=False`, `actions=True`, `repair=False`,
  `prepost=False` 요청 옵션. 이전 기본 동작을 명시적으로 지정한다.
- 공급자가 반환한 OHLCV와 존재하는 Adj Close·Dividends·Stock Splits·Capital Gains.
  원본 세션 라벨을 보존하고 분석용 표준화 프레임과 분리한다.
- 보존한 일봉 JSON의 SHA-256. 원본 공급자 HTTP 응답 전체의 해시가 아니라, 선택된
  가격 열을 소수점 정밀도 15로 직렬화한 증거의 해시다.
- 마지막 세션 날짜·시장 시간대·정규 마감 시각 경과 여부.

`raw_daily_bars`를 `json.dumps(value, sort_keys=True, separators=(",", ":"),
ensure_ascii=False, allow_nan=False)`로 직렬화한 UTF-8 바이트로 해시를 재현할 수 있다.
캐시 조회에서는 최초 수집 시각을 새 시각으로 바꾸지 않는다.

보고서 입력에는 전체 가격 증거를 보존한다. 새 추천 사이클의 최초 판단에는 해당 보고서
식별자와 가격 증거 요약·해시를 연결한다. 사이클을 재사용해 목표가를 갱신해도 최초
증거는 갱신하지 않는다. 포트폴리오 위험 입력에는 크기를 줄이기 위해 요약만 넣는다.

## 해석 경계

미국 16:00 America/New_York, 국내 15:30 Asia/Seoul을 기준으로 시각 경과만 기록한다.
미국 시간대 변환은 DST를 따른다. 휴일·단축 거래·특별 폐쇄를 검증한 달력이 아니므로
`exchange_calendar_verified=False`, 공급자의 최종 종가 확정도 검증하지 않았으므로
`provider_finality_verified=False`를 유지한다. 시각대 없는 수집 시각은 경과 여부를
`null`로 둔다. 마감 시각이 지났다는 값만으로 시세 확정이나 전략 유효성을 선언하지 않는다.

조정 옵션은 조정 기준 검증과 다르다. 공급자가 제공하지 않은 조정 기준시점은
`not_supplied_by_provider`, `price_basis_verified=False`로 보존한다. 기업행사 열이
없으면 사건이 없었다는 뜻이 아니다. 실제 계좌 배당·세금·환율·수수료 원장도 대체하지 않는다.

기존 캐시는 `price_lineage={}`로 읽는다. 새 코드를 배포해도 이미 제거된 과거
기업행사나 당시 설정을 복원하지 않는다. 당일 기존 캐시를 재사용하면 그 자료는 계속
증거 미보존 상태이며, 실제 새 공급자 조회가 발생할 때부터 기록된다.

## 검증 및 운영 영향

백엔드 635개 테스트와 Ruff·Black 검사 통과. 기업행사 보존, 캐시 왕복, 과거 캐시의
미확인 상태 유지, 마감 전후 구분, 보고서 연결, 최초 판단 불변성을 검증했다.

과거에 동결한 84개 티커의 71행 자료로 직렬화 크기를 측정한 결과 티커당 약
5.6~11.3KB(평균 8.8KB)가 추가됐다. 실제 저장량은 요청 이력 길이·보고서 종목 수에
따라 증가한다. 새 외부 호출은 추가하지 않으며 LLM 프롬프트에 이 원본 일봉을 넣지 않는다.

수집 증거를 남기기 시작하는 단계다. 국내 달력 독립 대조, 과거 조정 기준 복원,
실계좌 현금흐름 원장과 비용 차감 성과 검증은 별도 작업으로 남는다.
