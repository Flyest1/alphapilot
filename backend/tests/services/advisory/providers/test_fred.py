import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import pytest

from app.services.advisory.providers.fred import FredMacroProvider


class FakeResponse:
    def __init__(self, payload, final_url=None):
        self.payload = payload
        self.final_url = final_url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def geturl(self):
        return self.final_url or "https://api.stlouisfed.org/fred/series/observations"


def fred_payload(value="4.25"):
    return {
        "realtime_start": "2026-07-17",
        "realtime_end": "2026-07-17",
        "observation_start": "2026-01-01",
        "observation_end": "2026-07-17",
        "observations": [
            {
                "realtime_start": "2026-07-17",
                "realtime_end": "2026-07-17",
                "date": "2026-07-01",
                "value": value,
            }
        ],
    }


def test_fred_provider_fetches_allowlisted_series_and_preserves_metadata():
    requests = []

    def opener(request, timeout):
        requests.append((request, timeout))
        return FakeResponse(fred_payload())

    provider = FredMacroProvider(
        api_key="backend-only-key",
        opener=opener,
        now_provider=lambda: datetime(2026, 7, 17, 8, tzinfo=timezone.utc),
    )

    result = provider.fetch_context(["FEDFUNDS"], "2026-01-01", "2026-07-17")

    assert result["status"] == "ok"
    assert result["retrieved_at"] == "2026-07-17T08:00:00+00:00"
    assert result["series"][0]["series_id"] == "FEDFUNDS"
    assert result["series"][0]["units"] == "Percent"
    assert result["series"][0]["observations"] == [
        {
            "observation_date": "2026-07-01",
            "value": 4.25,
            "realtime_start": "2026-07-17",
            "realtime_end": "2026-07-17",
        }
    ]
    assert result["series"][0]["realtime_vintage"]["realtime_start"] == "2026-07-17"
    query = parse_qs(urlparse(requests[0][0].full_url).query)
    assert urlparse(requests[0][0].full_url).scheme == "https"
    assert urlparse(requests[0][0].full_url).hostname == "api.stlouisfed.org"
    assert query["series_id"] == ["FEDFUNDS"]
    assert query["api_key"] == ["backend-only-key"]
    assert requests[0][1] == 10.0


def test_fred_provider_missing_key_fails_closed_without_http_call():
    called = False

    def opener(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("HTTP must not run without a FRED key")

    provider = FredMacroProvider(api_key="", opener=opener)

    result = provider.fetch_context(["UNRATE"])

    assert result["status"] == "unavailable"
    assert result["series"] == []
    assert result["failures"] == [{"reason": "not_configured"}]
    assert called is False


def test_fred_provider_retries_transient_http_error_then_caches_result():
    attempts = 0
    pauses = []

    def opener(_request, timeout):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise HTTPError("https://api.stlouisfed.org", 503, "unavailable", {}, None)
        assert timeout == 10.0
        return FakeResponse(fred_payload())

    provider = FredMacroProvider(
        api_key="key",
        opener=opener,
        sleep=pauses.append,
        now_provider=lambda: datetime(2026, 7, 17, tzinfo=timezone.utc),
    )

    first = provider.fetch_context(["DGS10"], "2026-01-01", "2026-07-17")
    second = provider.fetch_context(["DGS10"], "2026-01-01", "2026-07-17")

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert attempts == 2
    assert pauses == [0.25]


def test_fred_provider_no_observations_and_unknown_series_fail_closed():
    provider = FredMacroProvider(
        api_key="key",
        opener=lambda *_args, **_kwargs: FakeResponse({"observations": []}),
    )

    result = provider.fetch_context(["INDPRO"])

    assert result["status"] == "empty"
    assert result["series"] == []
    assert result["failures"] == [{"series_id": "INDPRO", "reason": "no_data"}]
    with pytest.raises(ValueError, match="not allowlisted"):
        provider.fetch_context(["UNSAFE_SERIES"])


@pytest.mark.parametrize("value", [".", "nan", "inf", "-inf"])
def test_fred_provider_rejects_non_finite_or_missing_observations(value):
    provider = FredMacroProvider(
        api_key="key",
        opener=lambda *_args, **_kwargs: FakeResponse(fred_payload(value)),
    )

    result = provider.fetch_context(["INDPRO"])

    assert result["status"] == "empty"
    assert result["series"] == []


def test_fred_provider_returns_unavailable_after_bounded_network_retries():
    attempts = 0

    def opener(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise URLError("network unavailable")

    provider = FredMacroProvider(api_key="key", opener=opener, sleep=lambda _seconds: None)

    result = provider.fetch_context(["CPIAUCSL"])

    assert attempts == 3
    assert result["status"] == "unavailable"
    assert result["series"] == []
    assert result["failures"] == [{"series_id": "CPIAUCSL", "reason": "network"}]


def test_fred_provider_rejects_redirected_response_host_without_exposing_url():
    provider = FredMacroProvider(
        api_key="secret-key",
        opener=lambda *_args, **_kwargs: FakeResponse(
            fred_payload(),
            final_url="https://attacker.example/collect?api_key=secret-key",
        ),
        max_attempts=1,
    )

    result = provider.fetch_context(["FEDFUNDS"], "2026-01-01", "2026-07-17")

    assert result["status"] == "unavailable"
    assert result["failures"] == [{"series_id": "FEDFUNDS", "reason": "invalid_response"}]
    assert "secret-key" not in str(result)
