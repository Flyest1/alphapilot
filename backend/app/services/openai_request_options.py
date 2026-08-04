from typing import Any

MAX_REASONING_MODEL = "gpt-5.6-luna"


def build_completion_options(model: str) -> dict[str, Any]:
    if model.strip().lower() == MAX_REASONING_MODEL:
        return {"reasoning_effort": "max"}
    return {"temperature": 0.2}
