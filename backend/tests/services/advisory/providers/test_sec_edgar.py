import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.error import HTTPError

import pytest

from app.services.advisory.providers import sec_edgar
from app.services.advisory.providers.sec_edgar import (
    SEC_DEFAULT_MAX_PERSISTENT_ENTRIES,
    SEC_MAX_SUBMISSION_BYTES,
    SecEdgarError,
    SecEdgarProvider,
)


class FakeResponse:
    def __init__(self, payload, headers=None):
        self.payload = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        return self.payload


class FakeOpener:
    def __init__(self, responses):
        self.responses = {url: list(values) for url, values in responses.items()}
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        response = self.responses[request.full_url].pop(0)
        if isinstance(response, Exception):
            raise response
        return FakeResponse(response)


class NoopLimiter:
    def __init__(self):
        self.calls = 0

    def acquire(self):
        self.calls += 1


@pytest.fixture(autouse=True)
def isolate_default_submission_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(sec_edgar, "SEC_DEFAULT_SUBMISSION_CACHE_DIR", tmp_path / "sec-edgar")


def recent_filings(cik="0000320193"):
    return {
        "cik": cik,
        "name": "Example Corp",
        "filings": {
            "recent": {
                "form": ["8-K", "10-Q", "10-K", "NPORT-P"],
                "filingDate": ["2026-07-01", "2026-06-01", "2026-02-01", "2026-07-15"],
                "reportDate": ["2026-06-30", "2026-05-31", "2025-12-31", "2026-04-30"],
                "accessionNumber": [
                    "0000320193-26-000001",
                    "0000320193-26-000002",
                    "0000320193-26-000003",
                    "0000320193-26-000004",
                ],
                "primaryDocument": ["eightk.htm", "tenq.htm", "tenk.htm", "nport.xml"],
                "items": ["2.02,9.01", "", "", ""],
            }
        },
    }


def submission_url(accession):
    return (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        f"{accession.replace('-', '')}/{accession}.txt"
    )


def provider(responses, **kwargs):
    return SecEdgarProvider(
        user_agent="AlphaPilot test contact@example.com",
        opener=FakeOpener(responses),
        rate_limiter=NoopLimiter(),
        cache_ttl_seconds=3600,
        **kwargs,
    )


def test_company_metadata_companyfacts_and_ticker_mapping_are_cached():
    tickers_url = "https://www.sec.gov/files/company_tickers.json"
    submissions_url = "https://data.sec.gov/submissions/CIK0000320193.json"
    facts_url = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
    client = provider(
        {
            tickers_url: [json.dumps({"0": {"ticker": "EXM", "cik_str": 320193}})],
            submissions_url: [json.dumps(recent_filings())],
            facts_url: [json.dumps({"cik": 320193, "facts": {"us-gaap": {}}})],
        }
    )

    assert client.ticker_to_cik("exm") == "0000320193"
    assert client.ticker_to_cik("EXM") == "0000320193"
    assert client.get_submissions_metadata("EXM")["name"] == "Example Corp"
    assert client.get_companyfacts("EXM")["facts"] == {"us-gaap": {}}

    requested_urls = [request.full_url for request, _timeout in client.opener.requests]
    assert requested_urls.count(tickers_url) == 1
    assert client.opener.requests[0][0].get_header("User-agent") == client.user_agent


def test_filing_methods_return_complete_submission_evidence_and_ai_disclosures():
    tickers_url = "https://www.sec.gov/files/company_tickers.json"
    submissions_url = "https://data.sec.gov/submissions/CIK0000320193.json"
    eight_k = "Revenue increased. Management guidance expects continued margin improvement."
    ten_q = (
        "AI revenue increased 25% as our generative AI platform added new customer "
        "contract growth. "
        "Automation delivered cost reduction using a proprietary model."
    )
    ten_k = "Artificial intelligence remains a strategic opportunity."
    client = provider(
        {
            tickers_url: [json.dumps({"0": {"ticker": "EXM", "cik_str": 320193}})],
            submissions_url: [json.dumps(recent_filings())],
            submission_url("0000320193-26-000001"): ["<TEXT>" + eight_k + "</TEXT>"],
            submission_url("0000320193-26-000002"): ["<TEXT>" + ten_q + "</TEXT>"],
            submission_url("0000320193-26-000003"): ["<TEXT>" + ten_k + "</TEXT>"],
        }
    )

    filings = client.list_recent_filings("EXM", ("10-K", "10-Q", "8-K"))
    release = client.get_latest_earnings_release("EXM")
    disclosures = client.get_ai_disclosures("EXM")

    assert {filing["form"] for filing in filings} == {"10-K", "10-Q", "8-K"}
    assert all(filing["text"] for filing in filings)
    assert release["provider"] == "sec_edgar"
    assert release["guidance"].startswith("Management guidance")
    assert disclosures[0]["form"] == "10-Q"
    assert disclosures[0]["reported_figures"] == ["25%"]
    assert "ai_revenue_evidence" in disclosures[0]["metrics"]
    assert disclosures[0]["url"].startswith("https://www.sec.gov/Archives/")


def test_nport_returns_only_delayed_xml_holdings_and_stated_flow_fields():
    fund_tickers_url = "https://www.sec.gov/files/company_tickers_mf.json"
    submissions_url = "https://data.sec.gov/submissions/CIK0000320193.json"
    nport_url = submission_url("0000320193-26-000004")
    nport_text = """
    <DOCUMENT><TEXT><XML>
    <edgarSubmission>
      <invstOrSec><name>Example Holding</name><cusip>123456789</cusip>
      <valUSD>1234.5</valUSD><pctVal>4.2</pctVal></invstOrSec>
      <seriesId>S000000001</seriesId>
      <monthlyFlow><sales>88.5</sales><redemption>40</redemption></monthlyFlow>
    </edgarSubmission>
    </XML></TEXT></DOCUMENT>
    """
    client = provider(
        {
            fund_tickers_url: [
                json.dumps(
                    {
                        "fields": ["cik", "seriesId", "classId", "ticker"],
                        "data": [[320193, "S000000001", "C000000001", "FUND"]],
                    }
                )
            ],
            submissions_url: [json.dumps(recent_filings())],
            nport_url: [nport_text],
        },
        now_provider=lambda: datetime(2026, 7, 17, tzinfo=timezone.utc),
    )

    result = client.get_nport_delayed_data("FUND")

    assert result["status"] == "available"
    assert result["public_data_delay_days"] == 60
    assert result["series_id"] == "S000000001"
    assert result["holdings"] == [
        {
            "name": "Example Holding",
            "title": None,
            "cusip": "123456789",
            "value_usd": 1234.5,
            "weight_pct": 4.2,
        }
    ]
    assert result["flow_fields"] == {"sales": 88.5, "redemption": 40.0}


def test_retry_is_bounded_and_disallowed_urls_fail_closed():
    tickers_url = "https://www.sec.gov/files/company_tickers.json"
    retry_error = HTTPError(tickers_url, 429, "too many requests", {}, None)
    sleeps = []
    client = provider(
        {
            tickers_url: [
                retry_error,
                json.dumps({"0": {"ticker": "EXM", "cik_str": 320193}}),
            ]
        },
        sleep=sleeps.append,
    )

    assert client.ticker_to_cik("EXM") == "0000320193"
    assert sleeps == [0.5]
    with pytest.raises(SecEdgarError):
        client._get_bytes("https://example.com/not-sec")


def test_sec_provider_requires_declared_user_agent():
    with pytest.raises(ValueError):
        SecEdgarProvider(user_agent="")


def test_sec_provider_keeps_large_complete_submissions_bounded():
    client = SecEdgarProvider(user_agent="AlphaPilot test contact@example.com")

    assert client.max_submission_bytes == SEC_MAX_SUBMISSION_BYTES
    assert client.max_submission_bytes == 16 * 1024 * 1024
    assert client.max_persistent_entries == SEC_DEFAULT_MAX_PERSISTENT_ENTRIES
    assert client.max_persistent_entries == 256


def test_complete_submission_disk_cache_persists_and_rejects_tampering(tmp_path):
    accession = "0000320193-26-000001"
    url = submission_url(accession)
    cache_dir = tmp_path / "sec-edgar"
    first = provider(
        {url: ["<TEXT>original filing text</TEXT>"]},
        submission_cache_dir=cache_dir,
    )

    assert first.get_complete_submission_text("0000320193", accession) == "original filing text"

    reused = provider({}, submission_cache_dir=cache_dir)
    assert reused.get_complete_submission_text("0000320193", accession) == "original filing text"
    assert reused.opener.requests == []

    payload_path = next(cache_dir.rglob("*.txt"))
    payload_path.write_bytes(b"tampered")
    refreshed = provider(
        {url: ["<TEXT>refetched filing text</TEXT>"]},
        submission_cache_dir=cache_dir,
    )

    refreshed_text = refreshed.get_complete_submission_text("0000320193", accession)
    assert refreshed_text == "refetched filing text"
    assert len(refreshed.opener.requests) == 1


def test_complete_submission_cache_fails_closed_on_metadata_identity_mismatch(tmp_path):
    accession = "0000320193-26-000001"
    url = submission_url(accession)
    cache_dir = tmp_path / "sec-edgar"
    client = provider(
        {url: ["<TEXT>verified filing text</TEXT>"]},
        submission_cache_dir=cache_dir,
    )
    assert client.get_complete_submission_text("0000320193", accession) == "verified filing text"

    metadata_path = next(cache_dir.rglob("*.json"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["url"] = "https://www.sec.gov/Archives/edgar/data/1/invalid.txt"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    unavailable = provider(
        {url: [HTTPError(url, 404, "not found", {}, None)]},
        submission_cache_dir=cache_dir,
    )

    assert unavailable.get_complete_submission_text("0000320193", accession) is None


def test_same_accession_concurrent_cache_misses_fetch_once(tmp_path):
    accession = "0000320193-26-000001"

    class SlowOpener:
        def __init__(self):
            self.calls = 0
            self.lock = threading.Lock()

        def __call__(self, _request, timeout):
            assert timeout == 15.0
            with self.lock:
                self.calls += 1
            time.sleep(0.05)
            return FakeResponse("<TEXT>single official fetch</TEXT>")

    opener = SlowOpener()
    client = SecEdgarProvider(
        user_agent="AlphaPilot test contact@example.com",
        opener=opener,
        rate_limiter=NoopLimiter(),
        submission_cache_dir=tmp_path / "sec-edgar",
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _value: client.get_complete_submission_text("0000320193", accession),
                range(2),
            )
        )

    assert results == ["single official fetch", "single official fetch"]
    assert opener.calls == 1


def test_persistent_cache_evicts_oldest_complete_pair_at_entry_limit(tmp_path):
    accessions = [
        "0000320193-26-000001",
        "0000320193-26-000002",
        "0000320193-26-000003",
    ]
    cache_dir = tmp_path / "sec-edgar"
    client = provider(
        {
            submission_url(accession): [f"<TEXT>filing {index}</TEXT>"]
            for index, accession in enumerate(accessions, start=1)
        },
        submission_cache_dir=cache_dir,
        max_persistent_entries=2,
    )

    assert client.get_complete_submission_text("0000320193", accessions[0]) == "filing 1"
    time.sleep(0.01)
    assert client.get_complete_submission_text("0000320193", accessions[1]) == "filing 2"
    time.sleep(0.01)
    assert client.get_complete_submission_text("0000320193", accessions[2]) == "filing 3"

    payload_entries = {path.stem for path in cache_dir.rglob("*.txt")}
    metadata_entries = {path.stem for path in cache_dir.rglob("*.json")}
    assert payload_entries == set(accessions[1:])
    assert metadata_entries == set(accessions[1:])


def test_persistent_cache_cleans_partial_pairs_and_abandoned_temp_files(tmp_path):
    cache_dir = tmp_path / "sec-edgar"
    cik_directory = cache_dir / "0000320193"
    cik_directory.mkdir(parents=True)
    orphan_payload = cik_directory / "0000320193-26-000010.txt"
    orphan_metadata = cik_directory / "0000320193-26-000011.json"
    abandoned_temp = cik_directory / ".0000320193-26-000012.txt.crashed"
    malformed_payload = cik_directory / "0000320193-26-000013.txt"
    malformed_metadata = cik_directory / "0000320193-26-000013.json"
    orphan_payload.write_bytes(b"orphan")
    orphan_metadata.write_text("{}", encoding="utf-8")
    abandoned_temp.write_bytes(b"partial")
    malformed_payload.write_bytes(b"malformed pair")
    malformed_metadata.write_text("{}", encoding="utf-8")
    accession = "0000320193-26-000001"
    client = provider(
        {submission_url(accession): ["<TEXT>complete filing</TEXT>"]},
        submission_cache_dir=cache_dir,
        max_persistent_entries=2,
    )

    assert client.get_complete_submission_text("0000320193", accession) == "complete filing"

    remaining_files = {path.name for path in cik_directory.iterdir()}
    assert remaining_files == {f"{accession}.txt", f"{accession}.json"}


def test_cache_cleanup_failure_does_not_fail_official_sec_fetch(tmp_path, monkeypatch):
    accession = "0000320193-26-000001"
    cache_dir = tmp_path / "sec-edgar"
    client = provider(
        {submission_url(accession): ["<TEXT>official filing</TEXT>"]},
        submission_cache_dir=cache_dir,
    )

    def fail_cleanup(*_args):
        raise OSError("cache cleanup unavailable")

    monkeypatch.setattr(client, "_prepare_submission_cache_write", fail_cleanup)

    assert client.get_complete_submission_text("0000320193", accession) == "official filing"
    assert list(cache_dir.rglob("*.*")) == []


def test_sgml_parser_keeps_document_boundaries_and_selects_earnings_exhibit():
    raw = """
    <DOCUMENT><TYPE>8-K
    <SEQUENCE>1
    <FILENAME>form8k.htm
    <TEXT><p>Item 2.02 results.</p></TEXT></DOCUMENT>
    <DOCUMENT><TYPE>EX-99.1
    <SEQUENCE>2
    <FILENAME>earnings.htm
    <TEXT><p>AI revenue increased 25%.</p></TEXT></DOCUMENT>
    """

    documents = SecEdgarProvider.parse_submission_documents(raw)
    selected = SecEdgarProvider._select_earnings_document(documents)

    assert [document["type"] for document in documents] == ["8-K", "EX-99.1"]
    assert selected["filename"] == "earnings.htm"
    assert selected["text"] == "AI revenue increased 25%."
    assert len(selected["sha256"]) == 64


def test_nport_fails_closed_on_series_mismatch_and_non_finite_values():
    fund_tickers_url = "https://www.sec.gov/files/company_tickers_mf.json"
    submissions_url = "https://data.sec.gov/submissions/CIK0000320193.json"
    nport_url = submission_url("0000320193-26-000004")
    client = provider(
        {
            fund_tickers_url: [
                json.dumps(
                    {
                        "fields": ["cik", "seriesId", "classId", "ticker"],
                        "data": [[320193, "S000000001", "C000000001", "FUND"]],
                    }
                )
            ],
            submissions_url: [json.dumps(recent_filings())],
            nport_url: [
                "<XML><edgarSubmission><seriesId>S999999999</seriesId>"
                "<monthlyFlow><sales>nan</sales></monthlyFlow></edgarSubmission></XML>"
            ],
        },
        now_provider=lambda: datetime(2026, 7, 17, tzinfo=timezone.utc),
    )

    result = client.get_nport_delayed_data("FUND")

    assert result["status"] == "unavailable"
    assert result["limitations"] == ["nport_text_unavailable"]
