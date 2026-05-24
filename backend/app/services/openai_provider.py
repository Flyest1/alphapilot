import json
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.models.report import ReportContent
from app.services.ai_provider import AIProvider
from app.utils.logging import log_external_failure


class OpenAIProvider(AIProvider):
    def __init__(
        self,
        api_key: str | None,
        model: str,
        client: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.client = client

    def generate_report(self, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        if self.client is None:
            if not self.api_key:
                raise RuntimeError("OpenAI API key is not configured")
            from openai import OpenAI

            self.client = OpenAI(api_key=self.api_key)

        try:
            content = self._call_openai(prompt, context)
            return json.loads(content)
        except Exception as exc:
            log_external_failure(
                "openai",
                exc,
                {"operation": "generate_report", "model": self.model},
            )
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=True,
    )
    def _call_openai(self, prompt: str, context: dict[str, Any]) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            response_format=self._response_format(),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an investment decision-support analyst. "
                        "Return only valid JSON matching the provided ReportContent schema. "
                        "Use exactly the schema field names. "
                        "Do not promise guaranteed profit."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "prompt": prompt,
                            "context": context,
                        },
                        default=str,
                    ),
                },
            ],
            temperature=0.2,
        )
        message = response.choices[0].message.content
        if not message:
            raise RuntimeError("OpenAI returned an empty response")
        return message

    def _response_format(self) -> dict[str, Any]:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "ReportContent",
                "schema": ReportContent.model_json_schema(),
            },
        }
