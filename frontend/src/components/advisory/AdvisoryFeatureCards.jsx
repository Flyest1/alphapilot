import { ADVISORY_FEATURES } from "./advisoryFeatures.js";

export default function AdvisoryFeatureCards({ children, selectedType, onSelect }) {
  return (
    <section aria-label="AI 자문 기능" className="advisory-feature-grid">
      {ADVISORY_FEATURES.map((feature, index) => (
        <div className="advisory-feature-item" key={feature.id}>
          <button
            aria-expanded={selectedType === feature.id}
            aria-pressed={selectedType === feature.id}
            className={`advisory-feature-card ${selectedType === feature.id ? "active" : ""}`}
            type="button"
            onClick={() => onSelect(feature.id)}
          >
            <span className="advisory-feature-number">{String(index + 1).padStart(2, "0")}</span>
            <strong>{feature.title}</strong>
            <small>{feature.description}</small>
            <span className="advisory-feature-tags">{feature.details.join(" · ")}</span>
          </button>
          {selectedType === feature.id &&
            (typeof children === "function" ? children(feature) : children)}
        </div>
      ))}
    </section>
  );
}
