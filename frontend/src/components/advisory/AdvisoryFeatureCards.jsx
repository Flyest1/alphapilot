import { ADVISORY_FEATURES } from "./advisoryFeatures.js";

export default function AdvisoryFeatureCards({ selectedType, onSelect }) {
  return (
    <section aria-label="AI 자문 기능" className="advisory-feature-grid">
      {ADVISORY_FEATURES.map((feature, index) => (
        <button
          aria-pressed={selectedType === feature.id}
          className={`advisory-feature-card ${selectedType === feature.id ? "active" : ""}`}
          key={feature.id}
          type="button"
          onClick={() => onSelect(feature.id)}
        >
          <span className="advisory-feature-number">{String(index + 1).padStart(2, "0")}</span>
          <strong>{feature.title}</strong>
          <small>{feature.description}</small>
          <span className="advisory-feature-tags">{feature.details.join(" · ")}</span>
        </button>
      ))}
    </section>
  );
}
