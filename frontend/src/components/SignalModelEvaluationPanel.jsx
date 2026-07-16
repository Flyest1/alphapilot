import Skeleton from "./Skeleton.jsx";
import {
  formatEvaluationValue,
  signalModelEvaluationView,
} from "../utils/signalModelEvaluation.js";

export default function SignalModelEvaluationPanel({ evaluation, error, isLoading = false }) {
  const view = signalModelEvaluationView(evaluation, error);

  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h2>그림자 평가</h2>
          <p>신호 모델의 과거·병행 평가를 확인하는 연구 화면입니다.</p>
        </div>
        <span className="status-pill warning">{view.status.label}</span>
      </div>
      <div className="inline-metrics" aria-label="그림자 평가 운영 원칙">
        <span className="status-pill warning">연구 전용</span>
        <span className="status-pill warning">운영 미반영</span>
        <span className="status-pill warning">수동 승격만</span>
      </div>
      {isLoading ? (
        <Skeleton label="그림자 평가 정보를 불러오는 중입니다." lines={2} />
      ) : (
        <>
          <p className="field-hint">{view.status.message}</p>
          <div className="metric-grid compact performance-summary">
            <div>
              <span>평가 기간</span>
              <strong>{view.period}</strong>
            </div>
            {view.versions.map((row) => (
              <div key={row.label}>
                <span>{row.label}</span>
                <strong>{formatEvaluationValue("version", row.value)}</strong>
              </div>
            ))}
            {view.counts.map((row) => (
              <div key={row.label}>
                <span>{row.label}</span>
                <strong>{row.value}</strong>
              </div>
            ))}
            {view.samples.map((row) => (
              <div key={row.label}>
                <span>{row.label}</span>
                <strong>{row.value}</strong>
              </div>
            ))}
            <div>
              <span>임계값 상태</span>
              <strong>{formatEvaluationValue("threshold_state", view.thresholdState)}</strong>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
