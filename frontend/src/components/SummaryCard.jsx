export default function SummaryCard({ label, value, tone = "neutral" }) {
  return (
    <section className={`summary-card ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </section>
  );
}
