import json
import socket
import ssl
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError

from tenacity import wait_none

from app.services.news_service import NewsService, _failure_reason, _is_retryable_news_error

FIXED_NOW = datetime(2026, 7, 12, 9, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload, socket_target=None):
        self.payload = payload
        self.fp = type("FakeFp", (), {})()
        self.fp.raw = type("FakeRaw", (), {"_sock": socket_target})()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FakeSocket:
    def __init__(self):
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout


def build_service(opener, **kwargs):
    return NewsService(opener=opener, pause_seconds=0, now_provider=lambda: FIXED_NOW, **kwargs)


def test_news_service_fetches_normalizes_and_configures_timeouts():
    calls = []
    read_socket = FakeSocket()

    def opener(request, timeout):
        calls.append((request, timeout))
        return FakeResponse(
            {
                "articles": [
                    {
                        "title": "NVIDIA demand rises",
                        "url": "https://EXAMPLE.com/ai-chip/?utm_source=gdelt&id=1#section",
                        "domain": "example.com",
                        "sourcecountry": "United States",
                        "language": "English",
                        "seendate": "20260712T080000Z",
                    }
                ]
            },
            socket_target=read_socket,
        )

    context = build_service(
        opener,
        connect_timeout_seconds=3,
        read_timeout_seconds=7,
    ).fetch_report_context("global", [{"market": "US", "ticker": "NVDA", "name": "NVIDIA"}])

    article = context["articles"][0]
    assert context["provider"] == "gdelt_doc_2_0"
    assert context["status"] == "ok"
    assert context["queries"] == [
        "(NVIDIA OR NVDA)",
        '"S&P 500"',
        "NASDAQ",
        '"Federal Reserve"',
        '"US inflation"',
        '"Treasury yields"',
    ]
    assert context["query_details"][0] == {
        "query": "(NVIDIA OR NVDA)",
        "scope": "asset",
        "asset_ticker": "NVDA",
        "asset_name": "NVIDIA",
        "subject_kind": "candidate",
    }
    assert article["query_scope"] == "asset"
    assert article["asset_ticker"] == "NVDA"
    assert article["headline_evidence"] == "NVIDIA demand rises"
    assert article["canonical_url"] == "https://example.com/ai-chip?id=1"
    assert article["collected_at"] == FIXED_NOW.isoformat()
    assert article["seen_at"] == "2026-07-12T08:00:00+00:00"
    assert calls[0][1] == 3
    assert calls[0][0].headers["User-agent"] == "AlphaPilot/0.1 investment-decision-support"
    assert read_socket.timeout == 7


def test_asset_and_market_queries_have_reserved_budget_in_input_order():
    service = build_service(lambda *_args, **_kwargs: FakeResponse({"articles": []}))
    assets = [
        {"id": "1", "ticker": "OWN1", "name": "Owned One"},
        {"id": "2", "ticker": "OWN2", "name": "Owned Two"},
        {"id": "1", "ticker": "OWN1", "name": "Owned One"},
        {"ticker": "CAND1", "name": "Candidate One"},
        {"ticker": "CAND2", "name": "Candidate Two"},
        {"ticker": "CAND3", "name": "Candidate Three"},
        {"ticker": "CAND4", "name": "Candidate Four"},
    ]

    details = service._build_query_details("global", assets)

    assert len(details) == 6
    assert [detail["asset_ticker"] for detail in details] == [
        "OWN1",
        "OWN2",
        "CAND1",
        None,
        None,
        None,
    ]
    assert [detail["scope"] for detail in details] == [
        "asset",
        "asset",
        "asset",
        "market",
        "market",
        "market",
    ]


def test_news_service_filters_stale_and_accidental_asset_matches():
    def opener(_request, timeout):
        assert timeout == 5
        return FakeResponse(
            {
                "articles": [
                    {
                        "title": "NVIDIA launches new platform",
                        "url": "https://example.com/keep",
                        "seendate": "20260712080000",
                    },
                    {
                        "title": "Chip market outlook improves",
                        "url": "https://example.com/no-match",
                        "seendate": "20260712080000",
                    },
                    {
                        "title": "NVIDIA old announcement",
                        "url": "https://example.com/stale",
                        "seendate": "20260701080000",
                    },
                ]
            }
        )

    context = build_service(opener, timeout_seconds=5).fetch_report_context(
        "global", [{"ticker": "NVDA", "name": "NVIDIA"}]
    )

    asset_articles = [
        article for article in context["articles"] if article["query_scope"] == "asset"
    ]
    assert [article["url"] for article in asset_articles] == ["https://example.com/keep"]
    exclusion_reasons = {article["exclusion_reason"] for article in context["excluded_articles"]}
    assert "asset_name_not_relevant" in exclusion_reasons
    assert "invalid_or_out_of_window" in exclusion_reasons


def test_news_service_dedupes_canonical_urls_and_similar_event_headlines():
    service = build_service(lambda *_args, **_kwargs: FakeResponse({"articles": []}))
    articles = [
        {"title": "NVIDIA shares rise on AI demand", "url": "https://news.example/a?utm_source=x"},
        {"title": "NVIDIA shares rise on AI demand", "url": "https://news.example/a"},
        {"title": "NVIDIA shares rise as AI demand grows", "url": "https://other.example/b"},
        {"title": "Federal Reserve signals policy pause", "url": "https://other.example/c"},
    ]

    deduped = service._dedupe_articles(articles)

    assert [article["url"] for article in deduped] == [
        "https://news.example/a?utm_source=x",
        "https://other.example/c",
    ]


def test_failure_taxonomy_and_retryability_are_deterministic():
    http_error = HTTPError("https://example.com", 503, "unavailable", {}, None)
    cases = [
        (socket.gaierror("missing host"), "dns", True),
        (ssl.SSLError("temporary TLS failure"), "tls", True),
        (ssl.SSLCertVerificationError("bad certificate"), "tls", False),
        (URLError(ssl.SSLCertVerificationError("bad certificate")), "tls", False),
        (socket.timeout("slow"), "timeout", True),
        (http_error, "http", True),
        (json.JSONDecodeError("bad", "{", 1), "parsing", False),
        (URLError(socket.timeout("slow")), "timeout", True),
    ]

    for error, expected_reason, expected_retryable in cases:
        assert _failure_reason(error) == expected_reason
        assert _is_retryable_news_error(error) is expected_retryable


def test_fetch_retries_transient_timeout_and_reports_structured_failure_details():
    calls = 0

    def opener(_request, timeout):
        assert timeout == 15
        nonlocal calls
        calls += 1
        raise socket.timeout("slow")

    service = build_service(opener)
    service._fetch_articles = NewsService._fetch_articles.retry_with(wait=wait_none()).__get__(
        service,
        NewsService,
    )

    context = service.fetch_report_context("global", [{"ticker": "NVDA", "name": "NVIDIA"}])

    assert calls == 12
    assert context["status"] == "unavailable"
    assert context["failure_count"] == 6
    assert context["failure_reasons"] == ["timeout"]
    assert context["failure_details"][0] == {
        "query": "(NVIDIA OR NVDA)",
        "query_scope": "asset",
        "category": "timeout",
        "retryable": True,
        "http_status": None,
    }


def test_mixed_success_returns_partial_and_invalid_timestamps_are_rejected():
    calls = 0

    def opener(_request, timeout):
        assert timeout == 15
        nonlocal calls
        calls += 1
        if calls == 2:
            raise HTTPError("https://example.com", 404, "missing", {}, None)
        return FakeResponse(
            {
                "articles": [
                    {
                        "title": "S&P 500 rises",
                        "url": f"https://example.com/{calls}",
                        "seendate": "20260712080000" if calls == 1 else "invalid",
                    }
                ]
            }
        )

    context = build_service(opener).fetch_report_context("global", [])

    assert context["status"] == "partial"
    assert context["failure_count"] == 1
    assert len(context["articles"]) == 1
    assert context["articles"][0]["evidence_level"] == "headline-only"


def test_one_failed_query_and_other_empty_queries_is_partial_not_unavailable():
    calls = 0

    def opener(_request, timeout):
        assert timeout == 15
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError("https://example.com", 404, "missing", {}, None)
        return FakeResponse({"articles": []})

    context = build_service(opener).fetch_report_context("global", [])

    assert context["status"] == "partial"
    assert context["articles"] == []
    assert context["failure_count"] == 1


def test_fetch_report_context_can_bound_advisory_query_count():
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)
        return FakeResponse({"articles": []})

    context = build_service(opener).fetch_report_context(
        "global",
        [],
        max_queries=1,
    )

    assert len(calls) == 1
    assert len(context["query_details"]) == 1


def test_similar_headlines_for_different_assets_are_not_deduplicated():
    service = build_service(lambda *_args, **_kwargs: FakeResponse({"articles": []}))
    articles = [
        {
            "title": "Company shares rise after earnings",
            "url": "https://example.com/a",
            "asset_ticker": "AAA",
        },
        {
            "title": "Company shares rise after earnings",
            "url": "https://example.com/b",
            "asset_ticker": "BBB",
        },
    ]

    assert len(service._dedupe_articles(articles)) == 2
