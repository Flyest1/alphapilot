from typing import Any


class AIProvider:
    def generate_report(self, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
