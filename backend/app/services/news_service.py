import json
import re
import socket
import ssl
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.utils.logging import log_external_failure

GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
MAX_NEWS_QUERIES = 6
RESERVED_ASSET_QUERIES = 3
RESERVED_MARKET_QUERIES = 3
MAX_ARTICLES_PER_QUERY = 3
MAX_CONTEXT_ARTICLES = 18
NEWS_TIMESPAN = "3d"
NEWS_QUERY_PAUSE_SECONDS = 5.5
RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}
TRACKING_QUERY_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
TITLE_TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)


def _failure_reason(exc: BaseException) -> str:
    if isinstance(exc, HTTPError):
        return "http"
    if isinstance(exc, URLError):
        return _failure_reason(exc.reason) if isinstance(exc.reason, BaseException) else "network"
    if isinstance(exc, socket.gaierror):
        return "dns"
    if isinstance(exc, ssl.SSLError):
        return "tls"
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError, ValueError)):
        return "parsing"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(exc, (ConnectionError, OSError)):
        return "network"
    return "unknown"


def _is_retryable_news_error(exc: BaseException) -> bool:
    if isinstance(exc, HTTPError):
        return exc.code in RETRYABLE_HTTP_STATUS
    if isinstance(exc, ssl.SSLCertVerificationError):
        return False
    if isinstance(exc, URLError) and isinstance(exc.reason, ssl.SSLCertVerificationError):
        return False
    return _failure_reason(exc) in {"dns", "tls", "timeout", "network"}


class NewsService:
    def __init__(
        self,
        opener: Any | None = None,
        timeout_seconds: float | None = None,
        pause_seconds: float = NEWS_QUERY_PAUSE_SECONDS,
        connect_timeout_seconds: float = 15,
        read_timeout_seconds: float = 10,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.opener = opener or urlopen
        # timeout_seconds remains supported for callers using the original API.
        self.connect_timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else connect_timeout_seconds
        )
        self.read_timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else read_timeout_seconds
        )
        self.pause_seconds = pause_seconds
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        current = self.now_provider()
        return (
            current.replace(tzinfo=timezone.utc)
            if current.tzinfo is None
            else current.astimezone(timezone.utc)
        )

    def fetch_report_context(
        self,
        report_type: str,
        assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        query_details = self._build_query_details(report_type, assets)
        collected_at = self._now()
        articles: list[dict[str, Any]] = []
        excluded_articles: list[dict[str, Any]] = []
        failures = 0
        failure_reasons: list[str] = []
        failure_details: list[dict[str, Any]] = []

        for index, query_detail in enumerate(query_details):
            try:
                selected, excluded = self._fetch_articles(query_detail, collected_at)
                articles.extend(selected)
                excluded_articles.extend(excluded)
            except Exception as exc:
                failures += 1
                reason = _failure_reason(exc)
                if reason not in failure_reasons:
                    failure_reasons.append(reason)
                failure_details.append(
                    {
                        "query": query_detail["query"],
                        "query_scope": query_detail["scope"],
                        "category": reason,
                        "retryable": _is_retryable_news_error(exc),
                        "http_status": exc.code if isinstance(exc, HTTPError) else None,
                    }
                )
                log_external_failure(
                    "gdelt",
                    exc,
                    {
                        "operation": "fetch_news",
                        "query": query_detail["query"],
                        "query_scope": query_detail["scope"],
                        "asset_ticker": query_detail.get("asset_ticker"),
                    },
                )
            if self.pause_seconds > 0 and index < len(query_details) - 1:
                time.sleep(self.pause_seconds)

        deduped_articles, duplicate_articles = self._dedupe_with_exclusions(articles)
        excluded_articles.extend(duplicate_articles)
        excluded_articles.extend(
            {**article, "exclusion_reason": "context_limit"}
            for article in deduped_articles[MAX_CONTEXT_ARTICLES:]
        )
        deduped_articles = deduped_articles[:MAX_CONTEXT_ARTICLES]
        if failures == len(query_details) and query_details:
            status = "unavailable"
        elif failures:
            status = "partial"
        else:
            status = "ok" if deduped_articles else "empty"

        return {
            "provider": "gdelt_doc_2_0",
            "status": status,
            "timespan": NEWS_TIMESPAN,
            "generated_at": collected_at.isoformat(),
            "queries": [detail["query"] for detail in query_details],
            "query_details": query_details,
            "articles": deduped_articles,
            "excluded_articles": excluded_articles,
            "failure_count": failures,
            "failure_reasons": failure_reasons,
            "failure_details": failure_details,
            "failures": failure_details,
            "usage_note": (
                "Use this as recent news and trend context only when relevant. "
                "Do not add a separate news_factors field."
            ),
        }

    def _build_queries(self, report_type: str, assets: list[dict[str, Any]]) -> list[str]:
        """Return the legacy query list while query_details carries scope metadata."""
        return [detail["query"] for detail in self._build_query_details(report_type, assets)]

    def _build_query_details(
        self,
        report_type: str,
        assets: list[dict[str, Any]],
    ) -> list[dict[str, str | None]]:
        asset_details = self._asset_query_details(assets)
        owned_details = [row for row in asset_details if row["subject_kind"] == "owned"]
        candidate_details = [row for row in asset_details if row["subject_kind"] == "candidate"]
        prioritized_assets = [*owned_details[:2], *candidate_details[:1]]
        prioritized_assets.extend(
            row
            for row in [*owned_details[2:], *candidate_details[1:]]
            if row not in prioritized_assets
        )
        market_details = [
            {
                "query": self._quote_topic(topic),
                "scope": "market",
                "asset_ticker": None,
                "asset_name": None,
            }
            for topic in self._market_topics(report_type)
        ]
        query_details = [
            *prioritized_assets[:RESERVED_ASSET_QUERIES],
            *market_details[:RESERVED_MARKET_QUERIES],
        ]
        remaining_slots = MAX_NEWS_QUERIES - len(query_details)
        if remaining_slots:
            spillover = [
                *prioritized_assets[RESERVED_ASSET_QUERIES:],
                *market_details[RESERVED_MARKET_QUERIES:],
            ]
            query_details.extend(spillover[:remaining_slots])
        return query_details

    def _asset_query_details(self, assets: list[dict[str, Any]]) -> list[dict[str, str | None]]:
        query_details: list[dict[str, str | None]] = []
        seen_assets: set[tuple[str, str]] = set()
        for asset in assets:
            ticker = str(asset.get("ticker") or "").strip()
            name = str(asset.get("name") or "").strip()
            identity = (ticker.casefold(), name.casefold())
            if not any(identity) or identity in seen_assets:
                continue
            seen_assets.add(identity)
            query = self._asset_query(ticker, name)
            if not query:
                continue
            query_details.append(
                {
                    "query": query,
                    "scope": "asset",
                    "asset_ticker": ticker or None,
                    "asset_name": name or None,
                    "subject_kind": "owned" if asset.get("id") is not None else "candidate",
                }
            )
        return query_details

    def _asset_query(self, ticker: str, name: str) -> str:
        quoted_name = self._quote_topic(name) if name else ""
        clean_ticker = ticker.replace('"', "").strip()
        if quoted_name and clean_ticker and clean_ticker.casefold() != name.casefold():
            return f"({quoted_name} OR {clean_ticker})"
        return quoted_name or clean_ticker

    def _market_topics(self, report_type: str) -> list[str]:
        if report_type == "domestic":
            return [
                "KOSPI",
                "KOSDAQ",
                "Korean semiconductor",
                "Korean interest rates",
                "KRW exchange rate",
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
        wait=wait_exponential(multiplier=5, min=5, max=10),
        retry=retry_if_exception(_is_retryable_news_error),
        reraise=True,
    )
    def _fetch_articles(
        self,
        query_detail: dict[str, str | None],
        collected_at: datetime,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        params = urlencode(
            {
                "query": query_detail["query"],
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
        with self.opener(request, timeout=self.connect_timeout_seconds) as response:
            self._set_read_timeout(response)
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("GDELT payload must be an object")
        rows = payload.get("articles", [])
        if not isinstance(rows, list):
            raise ValueError("GDELT articles must be a list")
        selected = []
        excluded = []
        for row in rows:
            if not isinstance(row, dict):
                excluded.append(
                    self._excluded_article(
                        query_detail,
                        {},
                        collected_at,
                        "invalid_row",
                    )
                )
                continue
            article, exclusion_reason = self._normalize_article(
                query_detail,
                row,
                collected_at,
            )
            if article is not None:
                selected.append(article)
            else:
                excluded.append(
                    self._excluded_article(
                        query_detail,
                        row,
                        collected_at,
                        exclusion_reason or "invalid_article",
                    )
                )
        return selected, excluded

    def _set_read_timeout(self, response: Any) -> None:
        for path in (("fp", "raw", "_sock"), ("fp", "_sock"), ("_fp", "fp", "raw", "_sock")):
            target = response
            for attribute in path:
                target = getattr(target, attribute, None)
                if target is None:
                    break
            if target is not None and callable(getattr(target, "settimeout", None)):
                target.settimeout(self.read_timeout_seconds)
                return

    def _normalize_article(
        self,
        query_detail: dict[str, str | None],
        row: dict[str, Any],
        collected_at: datetime,
    ) -> tuple[dict[str, Any] | None, str | None]:
        title = str(row.get("title") or "").strip()
        seen_at = self._parse_seen_at(row.get("seendate"))
        if not title:
            return None, "missing_title"
        if seen_at is None or self._is_stale(seen_at, collected_at):
            return None, "invalid_or_out_of_window"
        if query_detail["scope"] == "asset" and not self._asset_matches_headline(
            title,
            query_detail.get("asset_ticker"),
            query_detail.get("asset_name"),
        ):
            return None, "asset_name_not_relevant"
        url = row.get("url")
        return {
            "query": query_detail["query"],
            "query_scope": query_detail["scope"],
            "asset_ticker": query_detail.get("asset_ticker"),
            "asset_name": query_detail.get("asset_name"),
            "subject_kind": query_detail.get("subject_kind"),
            "title": title,
            "headline_evidence": title,
            "evidence_level": "headline-only",
            "url": url,
            "canonical_url": self._canonical_url(url),
            "domain": row.get("domain"),
            "source_country": row.get("sourcecountry") or row.get("sourceCountry"),
            "language": row.get("language"),
            "seen_at": seen_at.isoformat(),
            "collected_at": collected_at.isoformat(),
        }, None

    def _excluded_article(
        self,
        query_detail: dict[str, str | None],
        row: dict[str, Any],
        collected_at: datetime,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "query": query_detail["query"],
            "query_scope": query_detail["scope"],
            "asset_ticker": query_detail.get("asset_ticker"),
            "asset_name": query_detail.get("asset_name"),
            "subject_kind": query_detail.get("subject_kind"),
            "title": row.get("title"),
            "url": row.get("url"),
            "domain": row.get("domain"),
            "seen_at": row.get("seendate"),
            "collected_at": collected_at.isoformat(),
            "evidence_level": "headline-only",
            "exclusion_reason": reason,
        }

    def _is_stale(self, seen_at: Any, collected_at: datetime) -> bool:
        seen_datetime = seen_at if isinstance(seen_at, datetime) else self._parse_seen_at(seen_at)
        if seen_datetime is None:
            return True
        return bool(
            seen_datetime < collected_at - timedelta(days=3)
            or seen_datetime > collected_at + timedelta(minutes=5)
        )

    def _parse_seen_at(self, value: Any) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        clean = value.strip()
        try:
            if len(clean) == 16 and clean[8] == "T" and clean.endswith("Z"):
                return datetime.strptime(clean, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            if clean.isdigit() and len(clean) == 14:
                return datetime.strptime(clean, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            parsed = datetime.fromisoformat(clean.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    def _asset_matches_headline(
        self,
        title: str,
        ticker: str | None,
        name: str | None,
    ) -> bool:
        title_normalized = title.casefold()
        for candidate in (ticker, name):
            clean = str(candidate or "").strip()
            if len(clean) < 2:
                continue
            if clean.isdigit():
                continue
            if re.search(rf"(?<!\w){re.escape(clean.casefold())}(?!\w)", title_normalized):
                return True
        return False

    def _canonical_url(self, value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        parsed = urlsplit(value.strip())
        query_items = sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
            and key.casefold() not in TRACKING_QUERY_PARAMETERS
        )
        path = parsed.path.rstrip("/") or "/"
        scheme = parsed.scheme.casefold()
        host = (parsed.hostname or "").casefold()
        port = parsed.port
        netloc = (
            host
            if port is None or (scheme, port) in {("https", 443), ("http", 80)}
            else f"{host}:{port}"
        )
        return urlunsplit((scheme, netloc, path, urlencode(query_items), ""))

    def _dedupe_articles(self, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._dedupe_with_exclusions(articles)[0]

    def _dedupe_with_exclusions(
        self,
        articles: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        deduped: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        canonical_urls: set[str] = set()
        title_fingerprints: list[tuple[set[str], str | None]] = []
        for article in articles:
            canonical_url = article.get("canonical_url") or self._canonical_url(article.get("url"))
            if canonical_url and canonical_url in canonical_urls:
                excluded.append({**article, "exclusion_reason": "duplicate_url"})
                continue
            tokens = self._title_tokens(article.get("title"))
            if not tokens or any(
                article.get("asset_ticker") == existing_ticker
                and self._similar_event(tokens, existing_tokens)
                for existing_tokens, existing_ticker in title_fingerprints
            ):
                excluded.append({**article, "exclusion_reason": "similar_event"})
                continue
            if canonical_url:
                canonical_urls.add(canonical_url)
            title_fingerprints.append((tokens, article.get("asset_ticker")))
            deduped.append(article)
        return deduped, excluded

    def _title_tokens(self, title: Any) -> set[str]:
        if not isinstance(title, str):
            return set()
        return {token.casefold() for token in TITLE_TOKEN_PATTERN.findall(title)}

    def _similar_event(self, first: set[str], second: set[str]) -> bool:
        overlap = len(first & second)
        return overlap >= 3 and overlap / max(len(first), len(second)) >= 0.7
