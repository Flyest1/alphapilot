from types import SimpleNamespace

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


def test_openai_provider_uses_json_mode_and_parses_response():
    client = FakeClient()
    provider = OpenAIProvider(api_key="unused", model="gpt-5.4-mini", client=client)

    result = provider.generate_report("prompt", {"ticker": "AAPL"})

    assert result == {"ok": True}
    kwargs = client.chat.completions.kwargs
    assert kwargs["model"] == "gpt-5.4-mini"
    assert kwargs["response_format"] == {"type": "json_object"}
