// 여러 화면에서 같이 쓰는 UI 문자열 상수. (i18n 라이브러리는 도입하지 않는다)

export const STRATEGY_FILTER_LABELS = {
  ALL: "전체",
  BUY: "매수",
  HOLD: "보유",
  REDUCE: "축소",
  SELL: "매도",
  WATCH: "관찰",
  DATA_LIMITED: "데이터 제한",
};

export const HORIZON_LABELS = {
  short: "단기 5거래일",
  medium: "중기 20거래일",
  long: "장기 60거래일",
};

export const CYCLE_STATUS_LABELS = {
  active: "진행 중",
  hit_target: "목표 도달",
  hit_stop: "손절 도달",
  expired: "기간 만료",
  superseded: "대체됨",
};

export const MESSAGES = {
  loadingReports: "리포트를 불러오는 중입니다.",
  loadingStrategies: "전략을 불러오는 중입니다.",
  loadingDashboard: "포트폴리오 데이터를 불러오는 중입니다.",
  loadingComparison: "비교 데이터를 불러오는 중입니다.",
  refreshing: "최신 데이터를 확인하는 중입니다.",
  noReports: "아직 생성된 리포트가 없습니다.",
  noStrategies: "표시할 전략이 없습니다.",
  requestFailed: "요청에 실패했습니다.",
  networkFailed: "백엔드 연결에 실패했습니다. API URL, 토큰, CORS 설정을 확인하세요.",
  timeout: "요청 시간이 초과되었습니다. 백엔드가 깨어나는 중일 수 있으니 잠시 후 다시 시도하세요.",
  tokenRequired: "접속 토큰을 먼저 입력하세요.",
};

export function horizonLabel(horizon) {
  return HORIZON_LABELS[horizon] || horizon || "-";
}

export function cycleStatusLabel(status) {
  return CYCLE_STATUS_LABELS[status] || status;
}
