import json

import pytest

from app.services.advisory.openai_provider import OpenAIAdvisoryProvider


class FakeCompletions:
    def __init__(self, content):
        self.content = content
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        message = type("Message", (), {"content": self.content})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


class FakeClient:
    def __init__(self, content):
        self.chat = type("Chat", (), {"completions": FakeCompletions(content)})()


class SequenceCompletions:
    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.contents.pop(0)
        message = type("Message", (), {"content": content})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


def narrative_payload(summary="근거 기반 관찰 결과입니다."):
    return json.dumps(
        {
            "summary": summary,
            "summary_evidence_ids": ["market:1"],
            "key_findings": [
                {
                    "text": "매출 성장 근거를 확인했습니다.",
                    "point_type": "fact",
                    "evidence_ids": ["market:1"],
                }
            ],
            "key_risks": [
                {
                    "text": "일부 데이터가 누락됐습니다.",
                    "point_type": "limitation",
                    "evidence_ids": [],
                }
            ],
            "actions_to_consider": [
                {
                    "text": "추가 공시를 확인합니다.",
                    "point_type": "inference",
                    "evidence_ids": ["market:1"],
                }
            ],
            "limitations": ["일부 데이터 제한"],
            "disclaimer": "투자 의사결정 지원 정보입니다.",
        },
        ensure_ascii=False,
    )


def test_openai_advisory_provider_uses_separate_json_schema():
    client = FakeClient(narrative_payload())
    provider = OpenAIAdvisoryProvider(None, "gpt-test", client=client)

    result = provider.generate_narrative(
        "sector_outlook",
        {"rows": [], "evidence": [{"evidence_id": "market:1"}]},
    )

    assert result.summary == "근거 기반 관찰 결과입니다."
    schema = client.chat.completions.kwargs["response_format"]["json_schema"]
    assert schema["name"] == "AdvisoryNarrative"


def test_openai_advisory_provider_rejects_forbidden_language():
    provider = OpenAIAdvisoryProvider(
        None,
        "gpt-test",
        client=FakeClient(narrative_payload("반드시 매수해야 합니다.")),
    )

    with pytest.raises(ValueError, match="forbidden language"):
        provider.generate_narrative("sector_outlook", {"rows": []})


def test_openai_advisory_provider_rejects_unknown_evidence():
    provider = OpenAIAdvisoryProvider(None, "gpt-test", client=FakeClient(narrative_payload()))

    with pytest.raises(ValueError, match="unknown evidence"):
        provider.generate_narrative(
            "sector_outlook",
            {"evidence": [{"evidence_id": "market:2"}]},
        )


def test_openai_advisory_provider_rejects_unsupported_numbers():
    provider = OpenAIAdvisoryProvider(
        None,
        "gpt-test",
        client=FakeClient(narrative_payload("수익률은 12.5%입니다.")),
    )

    with pytest.raises(ValueError, match="unsupported number"):
        provider.generate_narrative(
            "sector_outlook",
            {"evidence": [{"evidence_id": "market:1"}]},
        )


def test_openai_advisory_provider_retries_once_after_grounding_failure():
    completions = SequenceCompletions(
        [
            narrative_payload("수익률은 12.5%입니다."),
            narrative_payload("근거 기반 관찰 결과입니다."),
        ]
    )
    client = type(
        "Client",
        (),
        {"chat": type("Chat", (), {"completions": completions})()},
    )()
    provider = OpenAIAdvisoryProvider(None, "gpt-test", client=client)

    result = provider.generate_narrative(
        "sector_outlook",
        {"evidence": [{"evidence_id": "market:1"}]},
    )

    assert result.summary == "근거 기반 관찰 결과입니다."
    assert len(completions.calls) == 2
    assert "근거 검증에 실패" in completions.calls[1]["messages"][-1]["content"]
