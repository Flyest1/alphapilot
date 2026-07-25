from datetime import datetime
import re
from typing import Any

# Postgres trims trailing zeros from the microsecond field, so timestamps such as
# "2026-07-16T15:30:00.12+00:00" reach us with 1-5 fractional digits. Python's
# fromisoformat only accepts exactly 3 or 6 digits before 3.11, and the deploy
# targets 3.10 (deploy/oracle/deploy_backend.sh), so pad the fraction first.
_FRACTION_PATTERN = re.compile(r"\.(\d+)")


def _normalize_fraction(value: str) -> str:
    def pad(match: re.Match[str]) -> str:
        digits = match.group(1)
        return f".{digits[:6].ljust(6, '0')}"

    return _FRACTION_PATTERN.sub(pad, value, count=1)


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = _normalize_fraction(str(value).replace("Z", "+00:00"))
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
