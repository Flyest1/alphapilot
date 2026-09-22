from pydantic import ValidationError

from app.models.account_ledger import LedgerEvent


def validate_events(rows: list[dict]) -> dict:
    if not isinstance(rows, list):
        raise ValueError("Events must be an array")
    events, errors = [], []
    for index, row in enumerate(rows):
        try:
            events.append(LedgerEvent.model_validate(row))
        except ValidationError as exc:
            errors.append(
                {
                    "row": index,
                    "fields": [list(error["loc"]) for error in exc.errors()],
                    "reason": "invalid_event",
                }
            )
    return {"events": events, "errors": errors}
