import { actionLabel, displayReportText } from "../api/reports.js";
import { formatReturn, formatValue } from "../utils/formatters.js";
import { confidenceBadge } from "../utils/recommendationStats.js";

const DATA_LIMITED_NOTE_PATTERN = /insufficient|short|data[-\s]?limited/i;

const CONSTRAINT_LABELS = {
  allocation: "자산 비중 한도",
  cash: "현금 한도",
  concentration: "집중도 한도",
  risk: "손실 한도",
  fixed_risk: "개별 손실 예산",
  remaining_portfolio_loss: "남은 포트폴리오 손실 예산",
  remaining_cash: "남은 현금 예산",
  max_asset: "단일 자산 비중",
  market_room: "시장 배분 여유",
  currency_room: "통화 배분 여유",
  sector_room: "섹터 집중도",
  liquidity: "평균 거래대금",
  beta: "포트폴리오 베타",
  correlated_factor: "동일 팩터 상관 노출",
  expected_value: "비용 차감 기대값",
};

const UNAVAILABLE_REASON_LABELS = {
  "data-limited": "데이터 제한",
  insufficient_data: "데이터 부족",
  insufficient_history: "과거 데이터 부족",
  short_history: "과거 데이터 기간 부족",
  unavailable: "산출 불가",
};

function nonNegativeNumber(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric >= 0 ? numeric : null;
}

function finiteNumber(value) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function displayNumber(value) {
  const numeric = nonNegativeNumber(value);
  return numeric == null ? "-" : formatValue(numeric);
}

function displayPercent(value) {
  const numeric = nonNegativeNumber(value);
  return numeric == null ? "-" : `${numeric.toFixed(2)}%`;
}

function displaySignedNumber(value) {
  const numeric = finiteNumber(value);
  return numeric == null ? "-" : formatValue(numeric);
}

function displaySignedPercent(value) {
  const numeric = finiteNumber(value);
  return numeric == null ? "-" : `${numeric.toFixed(2)}%`;
}

function displayFrequency(value) {
  const numeric = nonNegativeNumber(value);
  if (numeric == null) return "-";
  return `${(numeric <= 1 ? numeric * 100 : numeric).toFixed(2)}%`;
}

function formatRange(low, high) {
  if (low == null && high == null) return "-";
  return `${displayNumber(low)} - ${displayNumber(high)}`;
}

function isDataLimited(strategy) {
  return strategy.reasoning === "data-limited";
}

function performanceFor(strategy, performanceLogs) {
  return performanceLogs.find(
    (row) => row.ticker === strategy.ticker && row.action === strategy.action,
  );
}

function confidenceDetailText(detail) {
  const parts = [`기술 점수 기여 ${displayNumber(detail.technical_confidence)}`];
  if (nonNegativeNumber(detail.win_rate) != null) {
    parts.push(
      `과거 목표 도달 비율 ${Math.round(nonNegativeNumber(detail.win_rate) * 100)}% (종료 표본 ${displayNumber(
        detail.sample_size,
      )}건${detail.calibrated ? `, 보정계수 ×${displayNumber(detail.calibration_factor)}` : ", 보정 미적용"})`,
    );
  } else {
    parts.push("과거 목표 도달 표본 없음");
  }
  // The breakdown is specified as technical / news / history; the label stays
  // provider-neutral so no news site is named.
  parts.push(detail.news_context_used ? "뉴스 컨텍스트 반영" : "뉴스 컨텍스트 미반영");
  return parts.join(" · ");
}

function constraintLabel(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  return CONSTRAINT_LABELS[value.trim().toLowerCase()] || value.trim();
}

function bindingConstraintText(sizing) {
  const bindingConstraint = sizing.binding_constraint_label ?? sizing.binding_constraint;
  if (typeof bindingConstraint === "object" && bindingConstraint) {
    return constraintLabel(
      bindingConstraint.label ?? bindingConstraint.name ?? bindingConstraint.key,
    );
  }
  return constraintLabel(bindingConstraint);
}

function appliedCapsText(constraints) {
  const appliedCaps = constraints?.applied_caps ?? constraints?.applied_cap;
  if (Array.isArray(appliedCaps)) {
    const caps = appliedCaps
      .map((cap) => {
        if (typeof cap === "string") return constraintLabel(cap);
        if (!cap || typeof cap !== "object") return null;
        const label = constraintLabel(cap.label ?? cap.name ?? cap.key);
        const amount = displayNumber(cap.amount ?? cap.value ?? cap.limit);
        return label ? `${label}${amount === "-" ? "" : ` ${amount}`}` : null;
      })
      .filter(Boolean);
    return caps.length ? caps.join(", ") : null;
  }

  if (appliedCaps && typeof appliedCaps === "object") {
    const caps = Object.entries(appliedCaps)
      .map(([key, value]) => {
        const amount = displayNumber(value);
        return amount === "-" ? null : `${constraintLabel(key) || key} ${amount}`;
      })
      .filter(Boolean);
    return caps.length ? caps.join(", ") : null;
  }

  if (constraints && typeof constraints === "object") {
    const caps = Object.entries(constraints)
      .map(([key, value]) => {
        if (!value || typeof value !== "object" || value.status !== "available") return null;
        const amount = displayNumber(value.amount);
        return amount === "-" ? null : `${constraintLabel(key) || key} ${amount}`;
      })
      .filter(Boolean);
    return caps.length ? caps.join(", ") : null;
  }

  return constraintLabel(appliedCaps);
}

function unavailableReasonsText(constraints) {
  const reasons = constraints?.unavailable_reasons;
  const unavailableConstraints =
    constraints && typeof constraints === "object"
      ? Object.entries(constraints)
          .filter(
            ([, value]) => value && typeof value === "object" && value.status === "unavailable",
          )
          .map(([key]) => constraintLabel(key) || key)
      : [];
  const values = [...(Array.isArray(reasons) ? reasons : [reasons]), ...unavailableConstraints];
  const labels = values
    .filter((reason) => typeof reason === "string" && reason.trim())
    .map((reason) => UNAVAILABLE_REASON_LABELS[reason.trim()] || reason.trim());
  return labels.length ? labels.join(", ") : null;
}

function expectedValueMetric(expectedValue, keys, formatter = displayPercent) {
  const value = keys.map((key) => expectedValue[key]).find((item) => item != null);
  return formatter(value);
}

function ExpectedValueSummary({ expectedValue }) {
  if (!expectedValue || typeof expectedValue !== "object") return null;

  if (expectedValue.status !== "available") {
    return <p>기대값 미산출: 표본 또는 데이터 품질 부족</p>;
  }

  return (
    <div>
      <p>과거 검증 기반 시나리오 기대값(보장 아님)</p>
      <ul>
        <li>
          목표 도달 빈도:{" "}
          {expectedValueMetric(
            expectedValue,
            ["target_hit_frequency", "target_frequency", "target_hit_rate"],
            displayFrequency,
          )}
        </li>
        <li>
          손절 도달 빈도:{" "}
          {expectedValueMetric(
            expectedValue,
            ["stop_hit_frequency", "stop_frequency", "stop_hit_rate"],
            displayFrequency,
          )}
        </li>
        <li>
          기타 결과 빈도:{" "}
          {expectedValueMetric(
            expectedValue,
            ["other_frequency", "other_closed_frequency", "other_outcome_frequency", "other_rate"],
            displayFrequency,
          )}
        </li>
        <li>
          표본 수:{" "}
          {expectedValueMetric(
            expectedValue,
            ["sample_size", "outcome_sample_size"],
            displayNumber,
          )}
          건
        </li>
        <li>
          상승 시나리오:{" "}
          {expectedValueMetric(expectedValue, [
            "upside_pct",
            "expected_upside_pct",
            "target_return_pct",
          ])}
        </li>
        <li>
          하락 시나리오:{" "}
          {expectedValueMetric(expectedValue, [
            "downside_pct",
            "expected_downside_pct",
            "stop_return_pct",
          ])}
        </li>
        <li>
          비용:{" "}
          {expectedValueMetric(expectedValue, [
            "cost_pct",
            "expected_cost_pct",
            "estimated_cost_pct",
          ])}{" "}
        </li>
        <li>
          기대값(EV):{" "}
          {expectedValueMetric(
            expectedValue,
            ["ev_pct", "expected_value_pct", "expected_return_pct", "value_pct"],
            displaySignedPercent,
          )}
        </li>
      </ul>
    </div>
  );
}

function RiskMetricsSummary({ riskMetrics }) {
  if (!riskMetrics || typeof riskMetrics !== "object") return null;
  const metrics = [
    [
      "변동성",
      displayPercent(
        riskMetrics.volatility ?? riskMetrics.volatility_pct ?? riskMetrics.daily_volatility_pct,
      ),
    ],
    [
      "갭 위험",
      displayPercent(riskMetrics.gap ?? riskMetrics.gap_risk ?? riskMetrics.gap_risk_pct),
    ],
    ["베타", displaySignedNumber(riskMetrics.beta)],
    ["최대 상관계수", displaySignedNumber(riskMetrics.max_correlation)],
  ].filter(([, value]) => value !== "-");

  return metrics.length ? (
    <p>위험 지표: {metrics.map(([label, value]) => `${label} ${value}`).join(" · ")}</p>
  ) : null;
}

function PositionSizingSummary({ sizing }) {
  const suggestedMax = displayNumber(sizing.suggested_max_amount);
  const bindingConstraint = bindingConstraintText(sizing);
  const appliedCaps = appliedCapsText(sizing.constraints);
  const unavailableReasons = unavailableReasonsText(sizing.constraints);

  return (
    <div>
      <p>
        제안 상한: {suggestedMax} {typeof sizing.currency === "string" ? sizing.currency : ""}
      </p>
      {bindingConstraint && <p>결정 제약: {bindingConstraint}</p>}
      {nonNegativeNumber(sizing.risk_per_trade_pct) != null && (
        <p>1회 위험 예산 기준: {displayPercent(sizing.risk_per_trade_pct)}</p>
      )}
      {nonNegativeNumber(sizing.stop_distance_pct) != null && (
        <p>손절가까지 거리: {displayPercent(sizing.stop_distance_pct)}</p>
      )}
      {appliedCaps && <p>적용 한도: {appliedCaps}</p>}
      {unavailableReasons && <p>미산출 사유: {unavailableReasons}</p>}
      <RiskMetricsSummary riskMetrics={sizing.risk_metrics} />
      <ExpectedValueSummary expectedValue={sizing.expected_value} />
      <p>
        후보별 상한은 합산할 수 없으며, 다른 후보와 결합할 수 없는(non-combinable) 모델
        추정치입니다.
      </p>
      <p>손실 한도는 목표이며 실제 손실을 보장하지 않습니다. 주문 수량이 아닙니다.</p>
    </div>
  );
}

function dataQualityText(inputs) {
  const parts = [`제공자 ${inputs.provider || "-"}`];
  if (inputs.last_trading_date) {
    parts.push(`최근 거래일 ${String(inputs.last_trading_date).slice(0, 10)}`);
  }
  const note = typeof inputs.data_quality_note === "string" ? inputs.data_quality_note : "";
  parts.push(
    inputs.is_stale || DATA_LIMITED_NOTE_PATTERN.test(note) ? "데이터 제한" : "데이터 최신",
  );
  return parts.join(" · ");
}

export default function StrategyTable({ strategies = [], performanceLogs = [], inputsByTicker }) {
  if (!strategies.length) {
    return <p className="empty-state">표시할 전략이 없습니다.</p>;
  }

  return (
    <div className="strategy-accordion">
      {strategies.map((strategy) => {
        const performance = performanceFor(strategy, performanceLogs);
        const badge = confidenceBadge(strategy.confidence_detail);
        const inputs = inputsByTicker?.[strategy.ticker];
        return (
          <details
            className={`strategy-detail ${isDataLimited(strategy) ? "data-limited" : ""}`}
            key={`${strategy.ticker}-${strategy.action}-${strategy.reasoning}`}
          >
            <summary>
              <span>
                <strong>{strategy.ticker}</strong>
                <em>{strategy.name}</em>
              </span>
              <span className={`badge ${strategy.action.toLowerCase()}`}>
                {actionLabel(strategy.action)}
              </span>
              {isDataLimited(strategy) && <span className="status-pill warning">데이터 제한</span>}
              {!isDataLimited(strategy) && badge && (
                <span className={`status-pill ${badge.kind === "calibrated" ? "ok" : "warning"}`}>
                  {badge.label}
                </span>
              )}
            </summary>
            <dl>
              <div>
                <dt>현재가</dt>
                <dd>{displayNumber(strategy.current_price)}</dd>
              </div>
              <div>
                <dt>신호 점수</dt>
                <dd>{displayNumber(strategy.confidence)} /100</dd>
              </div>
              <div>
                <dt>매수 구간</dt>
                <dd>{formatRange(strategy.buy_range_low, strategy.buy_range_high)}</dd>
              </div>
              <div>
                <dt>목표가</dt>
                <dd>{displayNumber(strategy.target_price)}</dd>
              </div>
              <div>
                <dt>손절가</dt>
                <dd>{displayNumber(strategy.stop_loss)}</dd>
              </div>
              <div>
                <dt>1일 변화</dt>
                <dd>{formatReturn(performance?.return_after_1d)}</dd>
              </div>
              <div>
                <dt>5일 변화</dt>
                <dd>{formatReturn(performance?.return_after_5d)}</dd>
              </div>
              <div>
                <dt>20일 변화</dt>
                <dd>{formatReturn(performance?.return_after_20d)}</dd>
              </div>
              {strategy.position_sizing && (
                <div className="wide-definition">
                  <dt>검토용 투입 금액 상한(모델 추정)</dt>
                  <dd>
                    <PositionSizingSummary sizing={strategy.position_sizing} />
                  </dd>
                </div>
              )}
              {strategy.confidence_detail && !isDataLimited(strategy) && (
                <div className="wide-definition">
                  <dt>신호 점수 근거</dt>
                  <dd>{confidenceDetailText(strategy.confidence_detail)}</dd>
                </div>
              )}
              {inputs && (
                <div className="wide-definition">
                  <dt>데이터 신선도</dt>
                  <dd>{dataQualityText(inputs)}</dd>
                </div>
              )}
              {isDataLimited(strategy) && (
                <div className="wide-definition">
                  <dt>상태</dt>
                  <dd>{displayReportText(strategy.reasoning)}</dd>
                </div>
              )}
            </dl>
          </details>
        );
      })}
    </div>
  );
}
