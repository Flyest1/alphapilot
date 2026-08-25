import { ACTION_LABELS } from "../api/reports.js";
import { HORIZON_LABELS, SCORE_BAND_LABELS } from "../constants/strings.js";

export const MIN_SAMPLE_FOR_HEADLINE = 5;

export function groupTitle(group) {
  const action = ACTION_LABELS[group.action] || group.action;
  const horizon = HORIZON_LABELS[group.horizon] || group.horizon;
  const band = SCORE_BAND_LABELS[group.score_band] || group.score_band_label || group.score_band;
  return `${action} · ${horizon} · ${band}`;
}

// "BUY·중기·점수 70대 추천의 20일 승률 64% (표본 22건)" 식 핵심 문장을 만든다.
export function statsHeadlines(stats, limit = 4) {
  return (stats?.groups || [])
    .filter((group) => group.closed_count >= MIN_SAMPLE_FOR_HEADLINE && group.win_rate != null)
    .sort((a, b) => b.closed_count - a.closed_count)
    .slice(0, limit)
    .map((group) => {
      const winRate = Math.round(group.win_rate * 100);
      return {
        key: `${group.action}-${group.horizon}-${group.score_band}`,
        text: `${groupTitle(group)} 추천의 목표 도달 승률 ${winRate}% (종료 표본 ${group.closed_count}건)`,
        group,
      };
    });
}

export function confidenceBadge(detail) {
  if (!detail) return null;
  if (detail.calibrated) {
    if (Number(detail.calibration_factor) < 1) {
      return { kind: "warning", label: "과거 성과 경고" };
    }
    return { kind: "calibrated", label: "과거 성과 참고" };
  }
  return { kind: "uncalibrated", label: "성과 보정 미적용" };
}
