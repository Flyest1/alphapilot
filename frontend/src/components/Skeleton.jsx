// 공통 스켈레톤 로더: 데이터 로딩 중 텍스트 대신 자리 표시 블록을 보여준다.
export default function Skeleton({ lines = 3, label = "" }) {
  return (
    <div aria-busy="true" aria-label={label || "불러오는 중"} className="skeleton" role="status">
      {Array.from({ length: lines }, (_, index) => (
        <span className="skeleton-line" key={index} />
      ))}
      {label && <p className="field-hint">{label}</p>}
    </div>
  );
}
