import json

from app.services.news_service import NewsService


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_news_service_fetches_and_normalizes_gdelt_articles():
    calls = []

    def opener(url, timeout):
        calls.append((url, timeout))
        return FakeResponse(
            {
                "articles": [
                    {
                        "title": "AI chip demand rises",
                        "url": "https://example.com/ai-chip",
                        "domain": "example.com",
                        "sourcecountry": "United States",
                        "language": "English",
                        "seendate": "20260527000000",
                    }
                ]
            }
        )

    service = NewsService(opener=opener, timeout_seconds=3)

    context = service.fetch_report_context(
        "global",
        [{"market": "US", "ticker": "NVDA", "name": "NVIDIA"}],
    )

    assert context["provider"] == "gdelt_doc_2_0"
    assert context["status"] == "ok"
    assert context["articles"][0]["title"] == "AI chip demand rises"
    assert context["articles"][0]["source_country"] == "United States"
    assert calls
    assert calls[0][1] == 3


def test_news_service_deduplicates_articles_and_handles_failures():
    def opener(_url, timeout):
        assert timeout
        return FakeResponse(
            {
                "articles": [
                    {"title": "Duplicate", "url": "https://example.com/a"},
                    {"title": "Duplicate", "url": "https://example.com/a"},
                ]
            }
        )

    service = NewsService(opener=opener)

    context = service.fetch_report_context("domestic", [])

    assert context["status"] == "ok"
    assert len(context["articles"]) == 1


def test_news_service_returns_unavailable_when_provider_fails():
    service = NewsService()

    def fail(_query):
        raise OSError("network down")

    service._fetch_articles = fail

    context = service.fetch_report_context("global", [])

    assert context["status"] == "unavailable"
    assert context["articles"] == []
