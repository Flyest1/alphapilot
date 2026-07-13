import json
import logging
from typing import Any

logger = logging.getLogger("alphapilot")


def log_external_failure(service: str, error: Exception, context: dict[str, Any]) -> None:
    logger.error(
        json.dumps(
            {
                "service": service,
                "error": str(error),
                "context": context,
            },
            default=str,
        )
    )


def log_structured_event(service: str, event: str, context: dict[str, Any]) -> None:
    logger.info(
        json.dumps(
            {
                "service": service,
                "event": event,
                "context": context,
            },
            default=str,
        )
    )
