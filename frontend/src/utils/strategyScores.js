function finiteScore(value) {
  if (value == null || value === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric >= 0 && numeric <= 100 ? numeric : null;
}

// 승률 보정은 경고/참고 정보로만 사용한다. 전략 순위와 주 점수 표시는
// 보정 입력값을 기준으로 하며, 과거 리포트는 저장된 confidence로 폴백한다.
export function strategyBaseConfidence(strategy) {
  const detail = strategy?.confidence_detail;
  return (
    finiteScore(detail?.base_confidence) ??
    finiteScore(detail?.technical_confidence) ??
    finiteScore(strategy?.confidence)
  );
}

export function compareStrategyBaseConfidence(left, right) {
  const leftScore = strategyBaseConfidence(left);
  const rightScore = strategyBaseConfidence(right);
  if (leftScore == null && rightScore == null) return 0;
  if (leftScore == null) return 1;
  if (rightScore == null) return -1;
  return rightScore - leftScore;
}

export function downsideCalibration(strategy) {
  const detail = strategy?.confidence_detail;
  const factor = finiteScore(detail?.calibration_factor);
  if (!detail?.calibrated || factor == null || factor >= 1) return null;
  return {
    factor,
    confidence: finiteScore(strategy?.confidence),
  };
}
