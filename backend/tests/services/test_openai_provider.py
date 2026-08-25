from types import SimpleNamespace

import pytest

from app.services.openai_provider import OpenAIProvider


class FakeCompletions:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        message = SimpleNamespace(content='{"ok": true}')
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())


def test_openai_provider_uses_structured_output_schema_and_parses_response():
    client = FakeClient()
    provider = OpenAIProvider(api_key="unused", model="gpt-5.4-mini", client=client)

    result = provider.generate_report("prompt", {"ticker": "AAPL"})

    assert result == {"ok": True}
    kwargs = client.chat.completions.kwargs
    assert kwargs["model"] == "gpt-5.4-mini"
    response_format = kwargs["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "ReportContent"
    assert response_format["json_schema"]["schema"]["properties"]["asset_strategies"]
    assert kwargs["temperature"] == 0.2
    assert "reasoning_effort" not in kwargs


@pytest.mark.parametrize(
    "model",
    ["gpt-5.6", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"],
)
def test_openai_provider_uses_max_reasoning_effort_for_gpt_5_6_family(model):
    client = FakeClient()
    provider = OpenAIProvider(api_key="unused", model=model, client=client)

    provider.generate_report("prompt", {"ticker": "AAPL"})

    kwargs = client.chat.completions.kwargs
    assert kwargs["reasoning_effort"] == "max"
    assert "temperature" not in kwargs
