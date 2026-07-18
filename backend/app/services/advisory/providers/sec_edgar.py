from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from html import unescape
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

SEC_DATA_HOST = "data.sec.gov"
SEC_ARCHIVES_HOST = "www.sec.gov"
SEC_ALLOWED_HOSTS = frozenset({SEC_DATA_HOST, SEC_ARCHIVES_HOST})
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FUND_TICKERS_URL = "https://www.sec.gov/files/company_tickers_mf.json"
SEC_RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
SEC_MAX_REQUESTS_PER_SECOND = 5
SEC_MAX_SUBMISSION_BYTES = 16 * 1024 * 1024
SEC_DEFAULT_MAX_PERSISTENT_ENTRIES = 256
SEC_DEFAULT_MAX_PERSISTENT_BYTES = 1024 * 1024 * 1024
SEC_NPORT_PUBLIC_DELAY_DAYS = 60
SEC_DEFAULT_SUBMISSION_CACHE_DIR = Path(__file__).resolve().parents[4] / ".cache" / "sec-edgar"

_TAG_PATTERN = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_PATTERN = re.compile(
    r"<(?:script|style)\b[^>]*>.*?</(?:script|style)\s*>", re.I | re.S
)
_SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")
_NUMBER_PATTERN = re.compile(
    r"(?:\$\s*)?\d[\d,]*(?:\.\d+)?\s*(?:%|million|billion|thousand)?", re.I
)
_AI_TERMS = ("artificial intelligence", "generative ai", "ai ", " ai", "machine learning")
_GUIDANCE_TERMS = ("guidance", "outlook", "expect", "forecast")
_RISK_TERMS = ("risk", "uncertain", "may adversely", "could adversely", "headwind")
_FLOW_FIELDS = frozenset(
    {
        "sales",
        "redemption",
        "reinvestment",
    }
)
_SGML_DOCUMENT_PATTERN = re.compile(r"<DOCUMENT>(.*?)</DOCUMENT>", re.I | re.S)
_SGML_FIELD_PATTERN = re.compile(r"<(TYPE|SEQUENCE|FILENAME|DESCRIPTION)>\s*([^\r\n<]+)", re.I)
_SGML_TEXT_PATTERN = re.compile(r"<TEXT>(.*?)</TEXT>", re.I | re.S)
_CACHE_ENTRY_PATTERN = re.compile(r"(?P<accession>\d{10}-\d{2}-\d{6})\.(?P<suffix>txt|json)")
_CACHE_TEMP_PATTERN = re.compile(r"\.\d{10}-\d{2}-\d{6}\.(?:txt|json)\..+")


class SecEdgarError(RuntimeError):
    """Raised internally for a failed or unsafe SEC EDGAR request."""


class _ProcessRateLimiter:
    """A process-wide limiter shared by all default provider instances."""

    def __init__(
        self,
        requests_per_second: int = SEC_MAX_REQUESTS_PER_SECOND,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = 1 / requests_per_second
        self.monotonic = monotonic
        self.sleep = sleep
        self.lock = threading.Lock()
        self.next_request_at = 0.0

    def acquire(self) -> None:
        with self.lock:
            now = self.monotonic()
            wait_seconds = max(0.0, self.next_request_at - now)
            self.next_request_at = max(now, self.next_request_at) + self.interval
        if wait_seconds:
            self.sleep(wait_seconds)


class SecEdgarProvider:
    """Read-only SEC EDGAR provider for official JSON/XML and archive submissions.

    The provider deliberately accepts only SEC HTTPS hosts, uses a declared User-Agent,
    applies a process-wide five requests-per-second limit, and returns empty results when
    evidence cannot be safely retrieved. It never follows filing links or crawls HTML.
    """

    _process_rate_limiter = _ProcessRateLimiter()
    _submission_locks: dict[str, tuple[threading.Lock, int]] = {}
    _submission_locks_guard = threading.Lock()
    _submission_cache_guard = threading.Lock()

    def __init__(
        self,
        user_agent: str,
        opener: Callable[..., Any] | None = None,
        timeout_seconds: float = 15.0,
        cache_ttl_seconds: float = 900.0,
        max_retries: int = 3,
        backoff_seconds: float = 0.5,
        max_backoff_seconds: float = 4.0,
        max_cache_entries: int = 256,
        max_persistent_entries: int = SEC_DEFAULT_MAX_PERSISTENT_ENTRIES,
        max_persistent_bytes: int = SEC_DEFAULT_MAX_PERSISTENT_BYTES,
        max_submission_bytes: int = SEC_MAX_SUBMISSION_BYTES,
        max_submission_text_chars: int = 750_000,
        submission_cache_dir: str | Path | None = None,
        rate_limiter: Any | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        normalized_user_agent = " ".join(user_agent.split())
        if not normalized_user_agent:
            raise ValueError("SEC EDGAR requests require a declared User-Agent")
        if timeout_seconds <= 0 or cache_ttl_seconds < 0:
            raise ValueError("SEC EDGAR timeout and cache TTL must be non-negative")
        if (
            max_retries < 1
            or max_cache_entries < 1
            or max_persistent_entries < 1
            or max_persistent_bytes < 1
        ):
            raise ValueError("SEC EDGAR retry and cache limits must be positive")
        if (
            max_submission_bytes < 1
            or max_submission_bytes > SEC_MAX_SUBMISSION_BYTES
            or max_submission_text_chars < 1
        ):
            raise ValueError("SEC EDGAR submission limits must be positive")

        self.user_agent = normalized_user_agent
        self.opener = opener or urlopen
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.max_cache_entries = max_cache_entries
        self.max_persistent_entries = max_persistent_entries
        self.max_persistent_bytes = max_persistent_bytes
        self.max_submission_bytes = max_submission_bytes
        self.max_submission_text_chars = max_submission_text_chars
        self.submission_cache_dir = Path(
            submission_cache_dir
            if submission_cache_dir is not None
            else SEC_DEFAULT_SUBMISSION_CACHE_DIR
        )
        self.rate_limiter = rate_limiter or self._process_rate_limiter
        self.sleep = sleep
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self._cache: dict[str, tuple[float, bytes]] = {}
        self._cache_lock = threading.Lock()
        try:
            with self._submission_cache_guard:
                self._prepare_submission_cache_write(
                    self.submission_cache_dir / ".startup-trim.txt",
                    self.submission_cache_dir / ".startup-trim.json",
                    0,
                    reserved_entries=0,
                )
        except OSError:
            pass

    def cache_status(self) -> dict[str, Any]:
        """Return bounded operational metadata without exposing cached filing contents."""
        with self._submission_cache_guard:
            entry_count = 0
            size_bytes = 0
            if self.submission_cache_dir.exists():
                for cik_directory in self.submission_cache_dir.iterdir():
                    if (
                        cik_directory.is_symlink()
                        or not cik_directory.is_dir()
                        or not re.fullmatch(r"\d{10}", cik_directory.name)
                    ):
                        continue
                    for payload_path in cik_directory.glob("*.txt"):
                        if payload_path.is_symlink() or not payload_path.is_file():
                            continue
                        match = _CACHE_ENTRY_PATTERN.fullmatch(payload_path.name)
                        if not match:
                            continue
                        metadata_path = payload_path.with_suffix(".json")
                        if not metadata_path.is_file() or metadata_path.is_symlink():
                            continue
                        try:
                            payload_size = payload_path.stat().st_size
                        except OSError:
                            continue
                        entry_count += 1
                        size_bytes += payload_size
            utilization_percent = (
                round(size_bytes / self.max_persistent_bytes * 100, 2)
                if self.max_persistent_bytes
                else 0.0
            )
            return {
                "status": "available",
                "entry_count": entry_count,
                "size_bytes": size_bytes,
                "max_entries": self.max_persistent_entries,
                "max_size_bytes": self.max_persistent_bytes,
                "utilization_percent": utilization_percent,
            }

    def ticker_to_cik(self, ticker: str) -> str | None:
        """Return the zero-padded SEC CIK for a listed ticker, or ``None`` on failure."""
        candidate = str(ticker or "").strip().upper()
        if candidate.isdigit() and len(candidate) <= 10:
            return candidate.zfill(10)
        if not candidate or not re.fullmatch(r"[A-Z0-9.\-]+", candidate):
            return None
        try:
            payload = self._get_json(SEC_TICKERS_URL)
        except SecEdgarError:
            return None
        for row in self._mapping_values(payload):
            if str(row.get("ticker") or "").upper() != candidate:
                continue
            cik = self._normalize_cik(row.get("cik_str"))
            if cik:
                return cik
        identity = self.get_fund_identity(candidate)
        return identity.get("cik") if identity else None

    def get_fund_identity(self, ticker: str) -> dict[str, str] | None:
        """Resolve a fund ticker to its SEC registrant, series and class identifiers."""
        candidate = str(ticker or "").strip().upper()
        if not candidate or not re.fullmatch(r"[A-Z0-9.\-]+", candidate):
            return None
        try:
            payload = self._get_json(SEC_FUND_TICKERS_URL)
        except SecEdgarError:
            return None
        for row in self._tabular_rows(payload):
            row_ticker = str(
                row.get("ticker") or row.get("symbol") or row.get("ticker_symbol") or ""
            ).upper()
            if row_ticker != candidate:
                continue
            cik = self._normalize_cik(row.get("cik") or row.get("cik_str"))
            series_id = str(
                row.get("seriesId") or row.get("series_id") or row.get("series") or ""
            ).strip()
            class_id = str(
                row.get("classId")
                or row.get("class_id")
                or row.get("class")
                or row.get("classContractId")
                or ""
            ).strip()
            if cik and re.fullmatch(r"S\d+", series_id, re.I):
                return {
                    "ticker": candidate,
                    "cik": cik,
                    "series_id": series_id.upper(),
                    "class_id": class_id.upper(),
                }
        return None

    def get_submissions_metadata(self, ticker: str) -> dict[str, Any]:
        """Return official company submissions metadata without fetching filing text."""
        cik = self.ticker_to_cik(ticker)
        if not cik:
            return {}
        try:
            payload = self._get_json(self._submissions_url(cik))
        except SecEdgarError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def get_companyfacts(self, ticker: str) -> dict[str, Any]:
        """Return the SEC companyfacts JSON payload, or an empty result when unavailable."""
        cik = self.ticker_to_cik(ticker)
        if not cik:
            return {}
        try:
            payload = self._get_json(f"https://{SEC_DATA_HOST}/api/xbrl/companyfacts/CIK{cik}.json")
        except SecEdgarError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def get_complete_submission_text(self, ticker_or_cik: str, accession_number: str) -> str | None:
        """Fetch and normalize one official complete-submission ``.txt`` archive file."""
        cik = self._resolve_cik(ticker_or_cik)
        accession = self._normalize_accession(accession_number)
        if not cik or not accession:
            return None
        try:
            raw = self._get_complete_submission_bytes(cik, accession)
        except SecEdgarError:
            return None
        return self.normalize_complete_submission_text(raw, self.max_submission_text_chars)

    def get_submission_documents(
        self, ticker_or_cik: str, accession_number: str
    ) -> list[dict[str, Any]]:
        """Return bounded SGML document blocks with stable hashes and normalized text."""
        cik = self._resolve_cik(ticker_or_cik)
        accession = self._normalize_accession(accession_number)
        if not cik or not accession:
            return []
        try:
            raw = self._get_complete_submission_bytes(cik, accession)
        except SecEdgarError:
            return []
        return self.parse_submission_documents(raw, self.max_submission_text_chars)

    def list_recent_filings(
        self,
        ticker: str,
        forms: Iterable[str] = ("10-K", "10-Q", "8-K"),
        limit_per_form: int = 2,
        lookback_days: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent selected filings with complete-submission evidence text.

        Results are intentionally limited per form so advisory analysis cannot turn one
        request into an unbounded archive download.
        """
        if limit_per_form < 1:
            return []
        requested_forms = {str(form).upper() for form in forms if str(form).strip()}
        if not requested_forms:
            return []
        cik = self.ticker_to_cik(ticker)
        if not cik:
            return []
        try:
            metadata = self._get_json(self._submissions_url(cik))
        except SecEdgarError:
            return []
        selected = self._select_recent_filings(
            metadata, requested_forms, limit_per_form=limit_per_form
        )
        if lookback_days is not None:
            cutoff = self._today() - timedelta(days=max(1, lookback_days))
            selected = [
                row for row in selected if self._date_on_or_after(row.get("filed_at"), cutoff)
            ]
        results = []
        for row in selected:
            documents = self.get_submission_documents(cik, str(row["accession_number"]))
            document = self._select_filing_document(documents, str(row["form"]))
            if not document:
                continue
            results.append(
                {
                    **row,
                    "text": document["text"],
                    "document_type": document["type"],
                    "document_sequence": document["sequence"],
                    "document_filename": document["filename"],
                    "document_sha256": document["sha256"],
                }
            )
        return results

    def get_latest_earnings_release(
        self, ticker: str, lookback_days: int | None = None
    ) -> dict[str, Any] | None:
        """Return the latest Item 2.02 8-K evidence without inferring market reactions."""
        cik = self.ticker_to_cik(ticker)
        if not cik:
            return None
        try:
            metadata = self._get_json(self._submissions_url(cik))
        except SecEdgarError:
            return None
        filings = self._select_recent_filings(metadata, {"8-K"}, limit_per_form=8)
        if lookback_days is not None:
            cutoff = self._today() - timedelta(days=max(1, lookback_days))
            filings = [
                row for row in filings if self._date_on_or_after(row.get("filed_at"), cutoff)
            ]
        filing = next((row for row in filings if "2.02" in str(row.get("items") or "")), None)
        if filing is None:
            return None
        documents = self.get_submission_documents(cik, str(filing["accession_number"]))
        document = self._select_earnings_document(documents)
        if not document:
            return None
        text = document["text"]
        guidance = self._first_sentence(text, _GUIDANCE_TERMS)
        highlights = self._sentences(text, ("revenue", "earnings", "margin", "cash flow"), 3)
        return {
            **filing,
            "provider": "sec_edgar",
            "document_type": document["type"],
            "document_filename": document["filename"],
            "document_sha256": document["sha256"],
            "guidance": guidance,
            "management_highlights": highlights,
            "key_risks": self._sentences(text, _RISK_TERMS, 3),
        }

    def get_ai_disclosures(self, ticker: str, limit: int = 6) -> list[dict[str, Any]]:
        """Return filing-backed AI disclosures with only directly stated numeric evidence."""
        if limit < 1:
            return []
        filings = self.list_recent_filings(ticker, ("10-K", "10-Q", "8-K"), limit_per_form=2)
        disclosures = []
        for filing in filings:
            sentences = self._sentences(str(filing.get("text") or ""), _AI_TERMS, 12)
            if not sentences:
                continue
            quantitative_sentences = [
                sentence for sentence in sentences if _NUMBER_PATTERN.search(sentence)
            ]
            metrics = self._direct_ai_metrics(quantitative_sentences)
            disclosures.append(
                {
                    "form": filing.get("form"),
                    "filed_at": filing.get("filed_at"),
                    "as_of": filing.get("report_date") or filing.get("filed_at"),
                    "accession_number": filing.get("accession_number"),
                    "url": filing.get("url"),
                    "text": " ".join(sentences),
                    "metrics": metrics,
                    "reported_figures": [
                        match.group(0).strip()
                        for sentence in quantitative_sentences
                        for match in _NUMBER_PATTERN.finditer(sentence)
                    ][:10],
                    "provider": "sec_edgar",
                }
            )
            if len(disclosures) >= limit:
                break
        return disclosures

    def get_nport_delayed_holdings(self, ticker: str, limit: int = 1) -> dict[str, Any]:
        """Expose delayed N-PORT holdings and stated flow fields when archive XML is parseable."""
        if limit < 1:
            return self._nport_unavailable(ticker, "invalid_limit")
        identity = self.get_fund_identity(ticker)
        if not identity:
            return self._nport_unavailable(ticker, "fund_series_not_found")
        cik = identity["cik"]
        try:
            metadata = self._get_json(self._submissions_url(cik))
        except SecEdgarError:
            return self._nport_unavailable(ticker, "submissions_unavailable")
        cutoff = self._today() - timedelta(days=SEC_NPORT_PUBLIC_DELAY_DAYS)
        rows = [
            row
            for row in self._select_recent_filings(metadata, {"NPORT-P", "NPORT-P/A"}, 12)
            if self._filing_is_delayed(row, cutoff)
        ][:limit]
        if not rows:
            return self._nport_unavailable(ticker, "no_delayed_nport_filing")

        parsed_filings = []
        holdings: list[dict[str, Any]] = []
        flow_fields: dict[str, float] = {}
        for row in rows:
            try:
                raw = self._get_complete_submission_bytes(cik, str(row["accession_number"]))
            except SecEdgarError:
                continue
            parsed_holdings, parsed_flows, series_ids = self._parse_nport_submission(
                raw.decode("utf-8", errors="replace")
            )
            if identity["series_id"] not in series_ids:
                continue
            parsed_filings.append({**row, "holdings_count": len(parsed_holdings)})
            holdings.extend(parsed_holdings)
            flow_fields.update(parsed_flows)
        if not parsed_filings:
            return self._nport_unavailable(ticker, "nport_text_unavailable")
        return {
            "provider": "sec_edgar",
            "ticker": str(ticker).upper(),
            "cik": cik,
            "series_id": identity["series_id"],
            "class_id": identity["class_id"],
            "status": "available" if holdings or flow_fields else "data_limited",
            "public_data_delay_days": SEC_NPORT_PUBLIC_DELAY_DAYS,
            "filings": parsed_filings,
            "holdings": holdings[:500],
            "flow_fields": flow_fields,
            "limitations": (
                []
                if holdings or flow_fields
                else ["N-PORT XML contained no safely recognized holdings or flow fields."]
            ),
        }

    def get_nport_delayed_data(self, ticker: str, limit: int = 1) -> dict[str, Any]:
        """Compatibility seam for consumers requesting delayed N-PORT data."""
        return self.get_nport_delayed_holdings(ticker, limit=limit)

    @staticmethod
    def normalize_complete_submission_text(raw: bytes | str, max_chars: int = 750_000) -> str:
        """Normalize official archive text only; no browser or HTML crawling is performed."""
        if isinstance(raw, bytes):
            text = raw.decode("utf-8", errors="replace")
        else:
            text = str(raw)
        text = _SCRIPT_STYLE_PATTERN.sub(" ", text)
        text = _TAG_PATTERN.sub(" ", text)
        text = " ".join(unescape(text).replace("\x00", " ").split())
        return text[:max_chars]

    @classmethod
    def parse_submission_documents(
        cls, raw: bytes | str, max_chars: int = 750_000
    ) -> list[dict[str, Any]]:
        source = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        documents = []
        for block in _SGML_DOCUMENT_PATTERN.findall(source):
            metadata = {
                key.lower(): value.strip() for key, value in _SGML_FIELD_PATTERN.findall(block)
            }
            text_match = _SGML_TEXT_PATTERN.search(block)
            if not text_match:
                continue
            normalized = cls.normalize_complete_submission_text(text_match.group(1), max_chars)
            if not normalized:
                continue
            documents.append(
                {
                    "type": metadata.get("type"),
                    "sequence": metadata.get("sequence"),
                    "filename": metadata.get("filename"),
                    "description": metadata.get("description"),
                    "text": normalized,
                    "sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
                }
            )
        if documents:
            return documents
        normalized = cls.normalize_complete_submission_text(source, max_chars)
        return (
            [
                {
                    "type": None,
                    "sequence": None,
                    "filename": None,
                    "description": None,
                    "text": normalized,
                    "sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
                }
            ]
            if normalized
            else []
        )

    def _get_json(self, url: str) -> Any:
        payload = self._get_bytes(url)
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecEdgarError("SEC EDGAR returned invalid JSON") from exc

    def _get_bytes(self, url: str) -> bytes:
        self._validate_url(url)
        cached = self._cache_get(url)
        if cached is not None:
            return cached
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                self.rate_limiter.acquire()
                request = Request(
                    url,
                    headers={
                        "User-Agent": self.user_agent,
                        "Accept": "application/json, text/plain, application/xml, text/xml",
                        "Accept-Encoding": "gzip",
                    },
                )
                with self.opener(request, timeout=self.timeout_seconds) as response:
                    final_url = getattr(response, "geturl", lambda: url)()
                    self._validate_url(final_url)
                    payload = response.read(self.max_submission_bytes + 1)
                    if len(payload) > self.max_submission_bytes:
                        raise SecEdgarError("SEC EDGAR response exceeded the configured size limit")
                    headers = getattr(response, "headers", {})
                    encoding = str(getattr(headers, "get", lambda *_: "")("Content-Encoding") or "")
                    if encoding.lower() == "gzip":
                        with gzip.GzipFile(fileobj=BytesIO(payload)) as compressed:
                            payload = compressed.read(self.max_submission_bytes + 1)
                        if len(payload) > self.max_submission_bytes:
                            raise SecEdgarError(
                                "SEC EDGAR response exceeded the configured size limit"
                            )
                    self._cache_put(url, payload)
                    return payload
            except HTTPError as exc:
                retryable = exc.code in SEC_RETRYABLE_STATUS_CODES
                last_error = exc
            except (URLError, TimeoutError, OSError) as exc:
                retryable = True
                last_error = exc
            except (gzip.BadGzipFile, ValueError) as exc:
                raise SecEdgarError("SEC EDGAR response could not be decoded") from exc
            except SecEdgarError:
                raise
            if not retryable or attempt == self.max_retries - 1:
                raise SecEdgarError("SEC EDGAR request failed") from last_error
            self.sleep(min(self.max_backoff_seconds, self.backoff_seconds * (2**attempt)))
        raise SecEdgarError("SEC EDGAR request failed")

    def _resolve_cik(self, ticker_or_cik: str) -> str | None:
        candidate = str(ticker_or_cik or "").strip()
        if candidate.isdigit():
            return self._normalize_cik(candidate)
        return self.ticker_to_cik(candidate)

    @staticmethod
    def _normalize_cik(value: Any) -> str | None:
        text = str(value or "").strip()
        return text.zfill(10) if text.isdigit() and len(text) <= 10 else None

    @staticmethod
    def _normalize_accession(value: str) -> str | None:
        accession = str(value or "").strip()
        return accession if re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) else None

    @staticmethod
    def _submissions_url(cik: str) -> str:
        return f"https://{SEC_DATA_HOST}/submissions/CIK{cik}.json"

    @staticmethod
    def _complete_submission_url(cik: str, accession: str) -> str:
        return (
            f"https://{SEC_ARCHIVES_HOST}/Archives/edgar/data/{int(cik)}/"
            f"{accession.replace('-', '')}/{accession}.txt"
        )

    def _get_complete_submission_bytes(self, cik: str, accession: str) -> bytes:
        normalized_cik = self._normalize_cik(cik)
        normalized_accession = self._normalize_accession(accession)
        if not normalized_cik or not normalized_accession:
            raise SecEdgarError("SEC EDGAR accession identity is invalid")
        url = self._complete_submission_url(normalized_cik, normalized_accession)
        with self._submission_fetch_lock(url):
            cached = self._read_submission_cache(normalized_cik, normalized_accession, url)
            if cached is not None:
                return cached
            payload = self._get_bytes(url)
            if len(payload) > SEC_MAX_SUBMISSION_BYTES:
                raise SecEdgarError("SEC EDGAR submission exceeded the size limit")
            self._write_submission_cache(normalized_cik, normalized_accession, url, payload)
            return payload

    @contextmanager
    def _submission_fetch_lock(self, url: str) -> Iterable[None]:
        """Serialize same-accession cache misses across this single process."""
        with self._submission_locks_guard:
            lock, references = self._submission_locks.get(url, (threading.Lock(), 0))
            self._submission_locks[url] = (lock, references + 1)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            with self._submission_locks_guard:
                current_lock, references = self._submission_locks[url]
                if current_lock is lock and references == 1:
                    self._submission_locks.pop(url, None)
                elif current_lock is lock:
                    self._submission_locks[url] = (lock, references - 1)

    def _submission_cache_paths(self, cik: str, accession: str) -> tuple[Path, Path]:
        directory = self.submission_cache_dir / cik
        return directory / f"{accession}.txt", directory / f"{accession}.json"

    def _read_submission_cache(self, cik: str, accession: str, url: str) -> bytes | None:
        payload_path, metadata_path = self._submission_cache_paths(cik, accession)
        with self._submission_cache_guard:
            return self._read_submission_cache_unlocked(
                payload_path,
                metadata_path,
                cik,
                accession,
                url,
            )

    def _read_submission_cache_unlocked(
        self,
        payload_path: Path,
        metadata_path: Path,
        cik: str,
        accession: str,
        url: str,
    ) -> bytes | None:
        metadata = self._read_submission_cache_metadata(
            metadata_path,
            cik,
            accession,
            url,
        )
        if metadata is None:
            return None
        try:
            payload = payload_path.read_bytes()
        except OSError:
            return None
        if (
            len(payload) != metadata["size_bytes"]
            or len(payload) > SEC_MAX_SUBMISSION_BYTES
            or hashlib.sha256(payload).hexdigest() != metadata["sha256"]
        ):
            return None
        try:
            metadata_path.touch()
        except OSError:
            pass
        return payload

    def _write_submission_cache(self, cik: str, accession: str, url: str, payload: bytes) -> None:
        if len(payload) > SEC_MAX_SUBMISSION_BYTES:
            raise SecEdgarError("SEC EDGAR submission exceeded the size limit")
        if len(payload) > self.max_persistent_bytes:
            return
        payload_path, metadata_path = self._submission_cache_paths(cik, accession)
        metadata = {
            "cik": cik,
            "accession": accession,
            "url": url,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        with self._submission_cache_guard:
            payload_written = False
            try:
                payload_path.parent.mkdir(parents=True, exist_ok=True)
                self._prepare_submission_cache_write(
                    payload_path,
                    metadata_path,
                    len(payload),
                )
                self._atomic_write_bytes(payload_path, payload)
                payload_written = True
                self._atomic_write_bytes(
                    metadata_path,
                    json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                )
            except OSError:
                if payload_written:
                    self._best_effort_unlink(payload_path, metadata_path)
                # A local cache failure must not make official SEC evidence unusable.
                return

    def _prepare_submission_cache_write(
        self,
        target_payload_path: Path,
        target_metadata_path: Path,
        incoming_size_bytes: int,
        reserved_entries: int = 1,
    ) -> None:
        complete_pairs: list[tuple[int, Path, Path, int]] = []
        if not self.submission_cache_dir.exists():
            return
        for cik_directory in self.submission_cache_dir.iterdir():
            if (
                cik_directory.is_symlink()
                or not cik_directory.is_dir()
                or not re.fullmatch(r"\d{10}", cik_directory.name)
            ):
                continue
            entry_files: dict[str, dict[str, Path]] = {}
            for path in cik_directory.iterdir():
                if path.is_symlink() or not path.is_file():
                    continue
                if _CACHE_TEMP_PATTERN.fullmatch(path.name):
                    path.unlink()
                    continue
                match = _CACHE_ENTRY_PATTERN.fullmatch(path.name)
                if match:
                    entry_files.setdefault(match["accession"], {})[match["suffix"]] = path
            for accession, paths in entry_files.items():
                payload_path = paths.get("txt")
                metadata_path = paths.get("json")
                if payload_path is None or metadata_path is None:
                    self._unlink_existing(payload_path, metadata_path)
                    continue
                cik = cik_directory.name
                url = self._complete_submission_url(cik, accession)
                metadata = self._read_submission_cache_metadata(
                    metadata_path,
                    cik,
                    accession,
                    url,
                )
                if metadata is None or payload_path.stat().st_size != metadata["size_bytes"]:
                    self._unlink_existing(payload_path, metadata_path)
                    continue
                if payload_path == target_payload_path and metadata_path == target_metadata_path:
                    continue
                complete_pairs.append(
                    (
                        metadata_path.stat().st_mtime_ns,
                        payload_path,
                        metadata_path,
                        int(metadata["size_bytes"]),
                    )
                )

        total_size_bytes = sum(item[3] for item in complete_pairs)
        oldest_first = sorted(complete_pairs)
        eviction_count = 0
        while (
            len(complete_pairs) + reserved_entries - eviction_count > self.max_persistent_entries
            or total_size_bytes + incoming_size_bytes > self.max_persistent_bytes
        ) and eviction_count < len(oldest_first):
            total_size_bytes -= oldest_first[eviction_count][3]
            eviction_count += 1
        for _modified_at, payload_path, metadata_path, _size_bytes in oldest_first[:eviction_count]:
            payload_path.unlink()
            metadata_path.unlink()

    @staticmethod
    def _read_submission_cache_metadata(
        metadata_path: Path,
        cik: str,
        accession: str,
        url: str,
    ) -> dict[str, Any] | None:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(metadata, dict) or set(metadata) != {
            "accession",
            "cik",
            "sha256",
            "size_bytes",
            "url",
        }:
            return None
        if (
            metadata["cik"] != cik
            or metadata["accession"] != accession
            or metadata["url"] != url
            or not isinstance(metadata["size_bytes"], int)
            or metadata["size_bytes"] < 0
            or metadata["size_bytes"] > SEC_MAX_SUBMISSION_BYTES
            or not isinstance(metadata["sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", metadata["sha256"])
        ):
            return None
        return metadata

    @staticmethod
    def _unlink_existing(*paths: Path | None) -> None:
        for path in paths:
            if path is not None:
                path.unlink()

    @staticmethod
    def _best_effort_unlink(*paths: Path) -> None:
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def _atomic_write_bytes(path: Path, payload: bytes) -> None:
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                dir=path.parent,
                prefix=f".{path.name}.",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, path)
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in SEC_ALLOWED_HOSTS or parsed.username:
            raise SecEdgarError("SEC EDGAR URL is not allowlisted")
        if parsed.port not in (None, 443) or not parsed.path.startswith("/"):
            raise SecEdgarError("SEC EDGAR URL is not allowlisted")
        allowed_path = (
            parsed.hostname == SEC_DATA_HOST
            and (
                re.fullmatch(r"/submissions/CIK\d{10}\.json", parsed.path)
                or re.fullmatch(r"/api/xbrl/companyfacts/CIK\d{10}\.json", parsed.path)
            )
        ) or (
            parsed.hostname == SEC_ARCHIVES_HOST
            and (
                parsed.path in {"/files/company_tickers.json", "/files/company_tickers_mf.json"}
                or re.fullmatch(
                    r"/Archives/edgar/data/\d+/\d{18}/\d{10}-\d{2}-\d{6}\.txt",
                    parsed.path,
                )
            )
        )
        if not allowed_path:
            raise SecEdgarError("SEC EDGAR URL path is not allowlisted")

    def _cache_get(self, url: str) -> bytes | None:
        if self.cache_ttl_seconds == 0:
            return None
        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(url)
            if cached is None or cached[0] <= now:
                self._cache.pop(url, None)
                return None
            return cached[1]

    def _cache_put(self, url: str, payload: bytes) -> None:
        if self.cache_ttl_seconds == 0:
            return
        with self._cache_lock:
            if len(self._cache) >= self.max_cache_entries:
                self._cache.pop(next(iter(self._cache)))
            self._cache[url] = (time.monotonic() + self.cache_ttl_seconds, payload)

    @staticmethod
    def _mapping_values(value: Any) -> list[Mapping[str, Any]]:
        if isinstance(value, Mapping):
            return [row for row in value.values() if isinstance(row, Mapping)]
        return []

    @classmethod
    def _tabular_rows(cls, value: Any) -> list[Mapping[str, Any]]:
        if isinstance(value, Mapping):
            fields = value.get("fields")
            data = value.get("data")
            if isinstance(fields, list) and isinstance(data, list):
                return [
                    dict(zip((str(field) for field in fields), row, strict=False))
                    for row in data
                    if isinstance(row, list)
                ]
        return cls._mapping_values(value)

    @staticmethod
    def _select_filing_document(
        documents: list[dict[str, Any]], form: str
    ) -> dict[str, Any] | None:
        normalized_form = form.upper()
        return next(
            (
                document
                for document in documents
                if str(document.get("type") or "").upper() == normalized_form
            ),
            documents[0] if documents else None,
        )

    @staticmethod
    def _select_earnings_document(documents: list[dict[str, Any]]) -> dict[str, Any] | None:
        return next(
            (
                document
                for document in documents
                if str(document.get("type") or "").upper().startswith("EX-99")
            ),
            next(
                (
                    document
                    for document in documents
                    if str(document.get("type") or "").upper() == "8-K"
                ),
                documents[0] if documents else None,
            ),
        )

    def _select_recent_filings(
        self,
        metadata: Any,
        requested_forms: set[str],
        limit_per_form: int,
    ) -> list[dict[str, Any]]:
        recent = (
            metadata.get("filings", {}).get("recent", {}) if isinstance(metadata, Mapping) else {}
        )
        if not isinstance(recent, Mapping):
            return []
        forms = recent.get("form", [])
        if not isinstance(forms, list):
            return []
        selected: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        for index, form_value in enumerate(forms):
            form = str(form_value or "").upper()
            if form not in requested_forms or counts.get(form, 0) >= limit_per_form:
                continue
            accession = self._row_value(recent, "accessionNumber", index)
            normalized_accession = self._normalize_accession(accession)
            if not normalized_accession:
                continue
            counts[form] = counts.get(form, 0) + 1
            selected.append(
                {
                    "form": form,
                    "filed_at": self._row_value(recent, "filingDate", index),
                    "report_date": self._row_value(recent, "reportDate", index),
                    "accession_number": normalized_accession,
                    "primary_document": self._row_value(recent, "primaryDocument", index),
                    "items": self._row_value(recent, "items", index),
                    "url": self._complete_submission_url(
                        self._normalize_cik(metadata.get("cik")) or "0000000000",
                        normalized_accession,
                    ),
                }
            )
        return selected

    @staticmethod
    def _row_value(rows: Mapping[str, Any], key: str, index: int) -> str | None:
        values = rows.get(key)
        if not isinstance(values, list) or index >= len(values):
            return None
        value = values[index]
        return str(value) if value not in (None, "") else None

    @staticmethod
    def _sentences(text: str, terms: Iterable[str], limit: int) -> list[str]:
        normalized_terms = tuple(term.casefold() for term in terms)
        sentences = []
        for sentence in _SENTENCE_PATTERN.split(" ".join(text.split())):
            normalized = sentence.casefold()
            if any(term in normalized for term in normalized_terms):
                sentences.append(sentence[:500])
            if len(sentences) >= limit:
                break
        return sentences

    def _first_sentence(self, text: str, terms: Iterable[str]) -> str | None:
        matches = self._sentences(text, terms, 1)
        return matches[0] if matches else None

    def _today(self) -> date:
        current = self.now_provider()
        if current.tzinfo is not None:
            current = current.astimezone(timezone.utc)
        return current.date()

    @staticmethod
    def _date_on_or_after(value: Any, cutoff: date) -> bool:
        try:
            return date.fromisoformat(str(value or "")) >= cutoff
        except ValueError:
            return False

    @staticmethod
    def _direct_ai_metrics(sentences: list[str]) -> dict[str, Any]:
        patterns = {
            "ai_revenue_evidence": ("ai revenue", "revenue from ai", "ai-related revenue"),
            "ai_cost_evidence": ("ai cost reduction", "ai-driven savings", "ai productivity"),
            "ai_customer_evidence": (
                "ai customer",
                "ai contract",
                "generative ai customer",
                "generative ai contract",
            ),
        }
        metrics = {}
        for metric, phrases in patterns.items():
            matched = [
                sentence[:500]
                for sentence in sentences
                if any(phrase in sentence.casefold() for phrase in phrases)
            ]
            if matched:
                metrics[metric] = matched[:3]
        return metrics

    @staticmethod
    def _filing_is_delayed(filing: Mapping[str, Any], cutoff: date) -> bool:
        report_date = str(filing.get("report_date") or "")
        try:
            return date.fromisoformat(report_date) <= cutoff
        except ValueError:
            return False

    def _nport_unavailable(self, ticker: str, reason: str) -> dict[str, Any]:
        return {
            "provider": "sec_edgar",
            "ticker": str(ticker).upper(),
            "status": "unavailable",
            "public_data_delay_days": SEC_NPORT_PUBLIC_DELAY_DAYS,
            "filings": [],
            "holdings": [],
            "flow_fields": {},
            "limitations": [reason],
        }

    @staticmethod
    def _parse_nport_submission(
        text: str,
    ) -> tuple[list[dict[str, Any]], dict[str, float], set[str]]:
        if re.search(r"<!DOCTYPE|<!ENTITY", text, re.I):
            return [], {}, set()
        documents = re.findall(r"<XML>\s*(.*?)\s*</XML>", text, flags=re.I | re.S)
        documents.append(text)
        root = None
        for document in documents:
            try:
                root = ElementTree.fromstring(document)
                break
            except ElementTree.ParseError:
                continue
        if root is None:
            return [], {}, set()
        series_ids = {
            (element.text or "").strip().upper()
            for element in root.iter()
            if SecEdgarProvider._local_name(element.tag).casefold()
            in {"seriesid", "serieslei", "seriesidentifier"}
            and re.fullmatch(r"S\d+", (element.text or "").strip(), re.I)
        }
        holdings = []
        for element in root.iter():
            if SecEdgarProvider._local_name(element.tag) != "invstOrSec":
                continue
            values = {
                SecEdgarProvider._local_name(child.tag): (child.text or "").strip()
                for child in element.iter()
                if child is not element and (child.text or "").strip()
            }
            holding = {
                "name": values.get("name"),
                "title": values.get("title"),
                "cusip": values.get("cusip"),
                "value_usd": SecEdgarProvider._decimal(values.get("valUSD")),
                "weight_pct": SecEdgarProvider._decimal(values.get("pctVal")),
            }
            if any(value is not None for value in holding.values()):
                holdings.append(holding)
        flows = {}
        for element in root.iter():
            if SecEdgarProvider._local_name(element.tag).casefold() != "monthlyflow":
                continue
            for child in element.iter():
                name = SecEdgarProvider._local_name(child.tag).casefold()
                value = SecEdgarProvider._decimal((child.text or "").strip())
                if name in _FLOW_FIELDS and value is not None:
                    flows[name] = value
        return holdings, flows, series_ids

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    @staticmethod
    def _decimal(value: str | None) -> float | None:
        if not value:
            return None
        try:
            parsed = float(value.replace(",", ""))
            return parsed if math.isfinite(parsed) else None
        except ValueError:
            return None
