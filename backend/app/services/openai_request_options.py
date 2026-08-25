from typing import Any

GPT_5_6_MODEL_PREFIX = "gpt-5.6"
GPT_5_6_REASONING_EFFORT = "max"


def build_completion_options(model: str) -> dict[str, Any]:
    normalized_model = model.strip().lower()
    if normalized_model == GPT_5_6_MODEL_PREFIX or normalized_model.startswith(
        f"{GPT_5_6_MODEL_PREFIX}-"
    ):
        return {"reasoning_effort": GPT_5_6_REASONING_EFFORT}
    return {"temperature": 0.2}
