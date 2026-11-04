from datetime import datetime, timezone
from typing import Any


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (shared timestamp format for persisted rows)."""
    return datetime.now(timezone.utc).isoformat()
