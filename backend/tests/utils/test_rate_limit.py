from datetime import datetime, timezone

from app.utils.rate_limit import DailyEndpointRateLimiter


def test_daily_endpoint_rate_limiter_blocks_after_limit():
    limiter = DailyEndpointRateLimiter(max_per_day=2)
    now = datetime(2026, 5, 21, tzinfo=timezone.utc)

    assert limiter.allow("/api/reports/domestic/generate", now) is True
    assert limiter.allow("/api/reports/domestic/generate", now) is True
    assert limiter.allow("/api/reports/domestic/generate", now) is False
