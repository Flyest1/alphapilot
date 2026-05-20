import pytest

from app.services.ai_provider import AIProvider


def test_ai_provider_interface_requires_implementation():
    with pytest.raises(NotImplementedError):
        AIProvider().generate_report("prompt", {})
