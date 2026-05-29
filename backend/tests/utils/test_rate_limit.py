from datetime import datetime, timezone

from app.utils.rate_limit import DailyEndpointRateLimiter


def test_daily_endpoint_rate_limiter_blocks_after_limit():
    limiter = DailyEndpointRateLimiter(max_per_day=2)
    now = datetime(2026, 5, 21, tzinfo=timezone.utc)

    assert limiter.allow("/api/reports/domestic/generate", now) is True
    assert limiter.allow("/api/reports/domestic/generate", now) is True
    assert limiter.allow("/api/reports/domestic/generate", now) is False


def test_daily_endpoint_rate_limiter_prunes_old_dates():
    limiter = DailyEndpointRateLimiter(max_per_day=2)
    first_day = datetime(2026, 5, 21, tzinfo=timezone.utc)
    second_day = datetime(2026, 5, 22, tzinfo=timezone.utc)

    assert limiter.allow("/api/reports/domestic/generate", first_day) is True
    assert limiter.allow("/api/reports/domestic/generate", second_day) is True

    assert list(limiter.calls) == [("/api/reports/domestic/generate", "2026-05-22")]
