import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.utils.logging import log_external_failure

GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
MAX_NEWS_QUERIES = 8
MAX_ARTICLES_PER_QUERY = 3
MAX_CONTEXT_ARTICLES = 18
NEWS_TIMESPAN = "3d"


class NewsService:
    def __init__(self, opener: Any | None = None, timeout_seconds: int = 8) -> None:
        self.opener = opener or urlopen
        self.timeout_seconds = timeout_seconds

    def fetch_report_context(
        self,
        report_type: str,
        assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        queries = self._build_queries(report_type, assets)
        articles: list[dict[str, Any]] = []
        failures = 0

        for query in queries:
            try:
                articles.extend(self._fetch_articles(query))
            except Exception as exc:
                failures += 1
                log_external_failure(
                    "gdelt",
                    exc,
                    {"operation": "fetch_news", "query": query},
                )

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
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type(
            (ConnectionError, TimeoutError, OSError, json.JSONDecodeError)
        ),
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
        with self.opener(f"{GDELT_DOC_API_URL}?{params}", timeout=self.timeout_seconds) as response:
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
