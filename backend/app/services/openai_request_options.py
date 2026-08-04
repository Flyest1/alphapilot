from typing import Any

LUNA_MODEL = "gpt-5.6-luna"
LUNA_REASONING_EFFORT = "xhigh"


def build_completion_options(model: str) -> dict[str, Any]:
    if model.strip().lower() == LUNA_MODEL:
        return {"reasoning_effort": LUNA_REASONING_EFFORT}
    return {"temperature": 0.2}
