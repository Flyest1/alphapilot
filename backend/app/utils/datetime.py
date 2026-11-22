from datetime import datetime, timezone
import re
from typing import Any


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        # PostgreSQL omits trailing zeroes; Python 3.10 accepts only 3 or 6 fraction digits.
        stamp = re.sub(
            r"(?<=:\d{2})\.(\d{1,5})(?=Z|[+-]|$)",
            lambda match: "." + match[1].ljust(6, "0"),
            str(value),
        )
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def utc_now_iso() -> str:
    """Current UTC time as an ISO-8601 string (shared timestamp format for persisted rows)."""
    return datetime.now(timezone.utc).isoformat()
