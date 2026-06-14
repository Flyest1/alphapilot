function eventDate(value) {
  if (!value) return "-";
  return String(value).slice(0, 10);
}

export default function AssetEventsPanel({ eventContext }) {
  const events = eventContext?.events || [];
  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h2>배당·실적 일정</h2>
          <p>yfinance가 제공하는 보유 자산의 향후 60일 일정입니다.</p>
        </div>
        <div className="inline-metrics">
          <span>{events.length}개 일정</span>
        </div>
      </div>
      {events.length === 0 ? (
        <p className="empty-state">확인 가능한 향후 배당·실적 일정이 없습니다.</p>
      ) : (
        <div className="event-list">
          {events.slice(0, 8).map((event) => (
            <div className="event-row" key={`${event.ticker}-${event.event_type}-${event.date}`}>
              <div>
                <strong>{event.ticker}</strong>
                <span>{event.name}</span>
              </div>
              <span>{event.label}</span>
              <strong>{eventDate(event.date)}</strong>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
