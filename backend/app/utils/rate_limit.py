from datetime import datetime, timezone


class DailyEndpointRateLimiter:
    def __init__(self, max_per_day: int = 10) -> None:
        self.max_per_day = max_per_day
        self.calls: dict[tuple[str, str], int] = {}

    def allow(self, endpoint: str, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        key = (endpoint, current.date().isoformat())
        count = self.calls.get(key, 0)
        if count >= self.max_per_day:
            return False
        self.calls[key] = count + 1
        return True
