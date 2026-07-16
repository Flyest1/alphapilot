const UNAVAILABLE = "-";

const STATE_COPY = {
  not_configured: {
    label: "평가 미설정",
    message: "그림자 평가가 아직 설정되지 않았습니다.",
  },
  collecting: {
    label: "데이터 수집 중",
    message: "그림자 평가 결과를 수집하고 있습니다.",
  },
  review_ready: {
    label: "검토 준비",
    message: "평가 자료가 준비되었습니다. 운영 반영은 수동 검토로만 결정합니다.",
  },
  unavailable: {
    label: "사용 불가",
    message: "그림자 평가 데이터를 현재 사용할 수 없습니다.",
  },
};

const THRESHOLD_STATE_LABELS = {
  unconfigured: "미설정",
};

function record(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function firstValue(...values) {
  return values.find((value) => value !== null && value !== undefined && value !== "");
}

function versionValue(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const source = record(value);
    return firstValue(source.version, source.model_version, source.name);
  }
  return value;
}

function evaluationStatus(source, error) {
  if (error?.status === 404) {
    return {
      label: "기능 준비 중",
      message: "서버에 그림자 평가 API 또는 마이그레이션이 아직 준비되지 않았습니다.",
    };
  }
  if (error || source.availability === "unavailable") return STATE_COPY.unavailable;
  if (source.availability === "migration_required") {
    return {
      label: "마이그레이션 필요",
      message: "그림자 평가 데이터를 보려면 서버 데이터베이스 마이그레이션이 필요합니다.",
    };
  }
  return STATE_COPY[source.state] || STATE_COPY.unavailable;
}

export function formatEvaluationValue(key, value) {
  if (value === null || value === undefined || value === "") return UNAVAILABLE;
  if (typeof value === "boolean") return value ? "예" : "아니오";
  if (key === "threshold_state" && THRESHOLD_STATE_LABELS[value]) {
    return THRESHOLD_STATE_LABELS[value];
  }

  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  if (/(rate|ratio|pct|percent|success|win)/i.test(key)) {
    const percentage = Math.abs(numeric) <= 1 ? numeric * 100 : numeric;
    return `${percentage.toFixed(2)}%`;
  }
  return numeric.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function signalModelEvaluationView(evaluation, error) {
  const source = error ? {} : record(evaluation);
  const activeEvaluation = record(source.active_evaluation);
  const samples = record(source.samples);
  const thresholds = record(source.thresholds);

  return {
    status: evaluationStatus(source, error),
    schemaVersion: source.schema_version,
    period:
      source.evaluation_window_weeks == null ? UNAVAILABLE : `${source.evaluation_window_weeks}주`,
    versions: [
      { label: "챔피언", value: versionValue(source.champion) },
      { label: "챌린저", value: versionValue(source.challenger) },
    ],
    counts: [
      {
        label: "예상 관측",
        value: formatEvaluationValue(
          "expected_observation_count",
          activeEvaluation.expected_observation_count,
        ),
      },
      {
        label: "관측 완료",
        value: formatEvaluationValue(
          "observed_observation_count",
          activeEvaluation.observed_observation_count,
        ),
      },
      {
        label: "제외 관측",
        value: formatEvaluationValue(
          "excluded_observation_count",
          activeEvaluation.excluded_observation_count,
        ),
      },
    ],
    samples: [
      {
        label: "정기 평가 표본",
        value: formatEvaluationValue("official_scheduled", samples.official_scheduled),
      },
      {
        label: "수동 입력 연결",
        value: formatEvaluationValue("manual_input_links", samples.manual_input_links),
      },
    ],
    thresholdState: thresholds.state,
  };
}
