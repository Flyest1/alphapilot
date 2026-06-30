import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.utils.logging import log_external_failure

GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
MAX_NEWS_QUERIES = 6
MAX_ARTICLES_PER_QUERY = 3
MAX_CONTEXT_ARTICLES = 18
NEWS_TIMESPAN = "3d"
NEWS_QUERY_PAUSE_SECONDS = 0.5
RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _is_retryable_news_error(exc: BaseException) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code in RETRYABLE_HTTP_STATUS
    return isinstance(exc, (ConnectionError, TimeoutError, OSError, json.JSONDecodeError))


class NewsService:
    def __init__(
        self,
        opener: Any | None = None,
        timeout_seconds: int = 5,
        pause_seconds: float = NEWS_QUERY_PAUSE_SECONDS,
    ) -> None:
        self.opener = opener or urlopen
        self.timeout_seconds = timeout_seconds
        self.pause_seconds = pause_seconds

    def fetch_report_context(
        self,
        report_type: str,
        assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        queries = self._build_queries(report_type, assets)
        articles: list[dict[str, Any]] = []
        failures = 0
        failure_reasons: list[str] = []

        for index, query in enumerate(queries):
            try:
                articles.extend(self._fetch_articles(query))
            except Exception as exc:
                failures += 1
                reason = _failure_reason(exc)
                if reason not in failure_reasons:
                    failure_reasons.append(reason)
                log_external_failure(
                    "gdelt",
                    exc,
                    {"operation": "fetch_news", "query": query},
                )
            if self.pause_seconds > 0 and index < len(queries) - 1:
                time.sleep(self.pause_seconds)

        deduped_articles = self._dedupe_articles(articles)[:MAX_CONTEXT_ARTICLES]
        status = "ok" if deduped_articles else "empty"
        if failures and not deduped_articles:
            status = "unavailable"

        return {
            "provider": "gdelt_doc_2_0",
            "status": status,
            "timespan": NEWS_TIMESPAN,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "queries": queries,
            "articles": deduped_articles,
            "failure_count": failures,
            "failure_reasons": failure_reasons,
            "usage_note": (
                "Use this as recent news and trend context only when relevant. "
                "Do not add a separate news_factors field."
            ),
        }

    def _build_queries(self, report_type: str, assets: list[dict[str, Any]]) -> list[str]:
        topics = self._market_topics(report_type)
        for asset in assets:
            name = str(asset.get("name") or "").strip()
            ticker = str(asset.get("ticker") or "").strip()
            if name:
                topics.append(name)
            if ticker and not ticker.isdigit():
                topics.append(ticker)

        unique_topics = []
        seen = set()
        for topic in topics:
            normalized = topic.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_topics.append(self._quote_topic(topic))
        return unique_topics[:MAX_NEWS_QUERIES]

    def _market_topics(self, report_type: str) -> list[str]:
        if report_type == "domestic":
            return [
                "코스피",
                "코스닥",
                "한국 반도체",
                "한국은행 금리",
                "원달러 환율",
                "South Korea exports",
            ]
        return [
            "S&P 500",
            "NASDAQ",
            "Federal Reserve",
            "US inflation",
            "Treasury yields",
            "AI semiconductor",
        ]

    def _quote_topic(self, topic: str) -> str:
        clean = topic.replace('"', "").strip()
        if " " in clean:
            return f'"{clean}"'
        return clean

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=3),
        retry=retry_if_exception(_is_retryable_news_error),
        reraise=True,
    )
    def _fetch_articles(self, query: str) -> list[dict[str, Any]]:
        params = urlencode(
            {
                "query": query,
                "mode": "artlist",
                "format": "json",
                "maxrecords": MAX_ARTICLES_PER_QUERY,
                "timespan": NEWS_TIMESPAN,
                "sort": "HybridRel",
            }
        )
        request = Request(
            f"{GDELT_DOC_API_URL}?{params}",
            headers={
                "User-Agent": "AlphaPilot/0.1 investment-decision-support",
                "Accept": "application/json",
            },
        )
        with self.opener(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return [self._normalize_article(query, row) for row in payload.get("articles", [])]

    def _normalize_article(self, query: str, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "query": query,
            "title": row.get("title"),
            "url": row.get("url"),
            "domain": row.get("domain"),
            "source_country": row.get("sourcecountry") or row.get("sourceCountry"),
            "language": row.get("language"),
            "seen_at": row.get("seendate"),
        }

    def _dedupe_articles(self, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped = []
        seen = set()
        for article in articles:
            marker = article.get("url") or article.get("title")
            if not marker or marker in seen:
                continue
            seen.add(marker)
            deduped.append(article)
        return deduped


def _failure_reason(exc: BaseException) -> str:
    if isinstance(exc, HTTPError):
        if exc.code == 429:
            return "rate_limited"
        return f"http_{exc.code}"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    return exc.__class__.__name__
