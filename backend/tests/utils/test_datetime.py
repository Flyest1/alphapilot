from datetime import datetime, timezone

import pytest

from app.utils.datetime import parse_iso_datetime


@pytest.mark.parametrize(
    "value",
    [
        "2026-07-16T15:30:00.12+00:00",
        "2026-07-16T15:30:00.1+00:00",
        "2026-07-16T15:30:00.12345+00:00",
        "2026-07-16T15:30:00.123456789+00:00",
    ],
)
def test_parse_iso_datetime_accepts_postgres_trimmed_fractions(value):
    """Postgres trims trailing zeros, and 3.10's fromisoformat wants 3 or 6 digits."""
    parsed = parse_iso_datetime(value)

    assert parsed is not None
    assert parsed.replace(microsecond=0) == datetime(2026, 7, 16, 15, 30, tzinfo=timezone.utc)


def test_parse_iso_datetime_still_rejects_garbage():
    assert parse_iso_datetime("not-a-timestamp") is None
    assert parse_iso_datetime(None) is None
