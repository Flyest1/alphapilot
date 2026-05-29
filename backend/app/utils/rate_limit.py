from datetime import datetime, timezone


class DailyEndpointRateLimiter:
    def __init__(self, max_per_day: int = 10) -> None:
        self.max_per_day = max_per_day
        self.calls: dict[tuple[str, str], int] = {}

    def allow(self, endpoint: str, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        current_date = current.date().isoformat()
        self._prune(current_date)
        key = (endpoint, current_date)
        count = self.calls.get(key, 0)
        if count >= self.max_per_day:
            return False
        self.calls[key] = count + 1
        return True

    def _prune(self, current_date: str) -> None:
        stale_keys = [key for key in self.calls if key[1] != current_date]
        for key in stale_keys:
            del self.calls[key]
