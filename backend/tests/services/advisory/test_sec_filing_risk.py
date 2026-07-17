from app.services.advisory.features.sec_filing_risk import SECFilingRiskAnalyzer

SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/1234567"


class FakeSECProvider:
    def list_recent_filings(self, _ticker, forms):
        assert forms == ("10-K", "10-Q", "8-K")
        return [
            {
                "form": "10-Q",
                "filed_at": "2026-06-01",
                "accession_number": "0001",
                "url": f"{SEC_ARCHIVES_URL}/000123456726000001/form10q.htm",
                "text": (
                    "Revenue decline and margin pressure may adversely affect results. "
                    "Our liquidity could materially affect operations. "
                    "We face regulatory investigation and supply chain shortage."
                ),
            },
            {
                "form": "10-Q",
                "filed_at": "2026-03-01",
                "accession_number": "0000",
                "url": f"{SEC_ARCHIVES_URL}/000123456726000000/form10q.htm",
                "text": "We face supply chain risk.",
            },
            {
                "form": "10-K",
                "filed_at": "2026-02-01",
                "accession_number": "k001",
                "url": f"{SEC_ARCHIVES_URL}/000123456726000002/form10k.htm",
                "text": "Customer concentration may adversely affect revenue.",
            },
            {
                "form": "8-K",
                "filed_at": "2026-06-10",
                "accession_number": "8k01",
                "url": f"{SEC_ARCHIVES_URL}/000123456726000003/form8k.htm",
                "text": "Negative cash flow and debt covenant uncertainty continue.",
            },
        ]


def test_sec_risk_analysis_covers_forms_categories_and_new_emphasis():
    result = SECFilingRiskAnalyzer(FakeSECProvider()).analyze("EXM")

    assert {row["form"] for row in result["latest_filings"]} == {"10-K", "10-Q", "8-K"}
    identified = {
        row["category"] for row in result["risk_categories"] if row["status"] == "identified"
    }
    assert "revenue_slowdown" in identified
    assert "liquidity" in identified
    assert "regulatory_litigation" in identified
    assert result["newly_emphasized_risks"]
    assert result["risk_rating"] == "high_risk"
    assert result["evaluation_status"] == "available"
    assert result["evidence"][0]["provider"] == "sec_edgar"


def test_sec_risk_analysis_fails_closed_without_provider():
    result = SECFilingRiskAnalyzer(None).analyze("EXM")

    assert result["risk_rating"] == "insufficient_data"
    assert result["evaluation_status"] == "unavailable"
    assert "evaluation unavailable" in result["rating_reason"]
    assert result["data_quality"]["status"] == "unavailable"
    assert result["latest_filings"] == []


class EmptySECProvider:
    def list_recent_filings(self, _ticker, _forms):
        return []


def test_sec_risk_analysis_fails_closed_without_filings():
    result = SECFilingRiskAnalyzer(EmptySECProvider()).analyze("EXM")

    assert result["risk_rating"] == "insufficient_data"
    assert result["evaluation_status"] == "unavailable"
    assert result["evidence"] == []


class PartialSECProvider:
    def list_recent_filings(self, _ticker, _forms):
        return [
            {
                "form": "10-Q",
                "filed_at": "2026-06-01",
                "text": "Liquidity may adversely affect results.",
            }
        ]


def test_sec_risk_analysis_requires_all_three_filing_forms():
    result = SECFilingRiskAnalyzer(PartialSECProvider()).analyze("EXM")

    assert result["risk_rating"] == "insufficient_data"
    assert result["evaluation_status"] == "unavailable"
    assert result["required_forms_complete"] is False
    assert result["missing_forms"] == ["10-K", "8-K"]


def test_sec_risk_analysis_fails_closed_without_accession_number():
    class MissingAccessionSECProvider(FakeSECProvider):
        def list_recent_filings(self, ticker, forms):
            filings = super().list_recent_filings(ticker, forms)
            filings[0].pop("accession_number")
            return filings

    result = SECFilingRiskAnalyzer(MissingAccessionSECProvider()).analyze("EXM")

    assert result["risk_rating"] == "insufficient_data"
    assert result["evaluation_status"] == "unavailable"
    assert result["missing_evidence"] == ["10-Q.accession_number"]
    assert result["data_quality"]["missing_fields"] == ["10-Q.accession_number"]
    assert "evidence integrity is incomplete" in result["data_quality"]["limitations"][0]


def test_sec_risk_analysis_fails_closed_without_official_archives_url():
    class MissingUrlSECProvider(FakeSECProvider):
        def list_recent_filings(self, ticker, forms):
            filings = super().list_recent_filings(ticker, forms)
            filings[0]["url"] = "https://example.test/10q-new"
            return filings

    result = SECFilingRiskAnalyzer(MissingUrlSECProvider()).analyze("EXM")

    assert result["risk_rating"] == "insufficient_data"
    assert result["evaluation_status"] == "unavailable"
    assert result["missing_evidence"] == ["10-Q.url"]
    assert result["data_quality"]["missing_fields"] == ["10-Q.url"]
    assert "evidence integrity is incomplete" in result["data_quality"]["limitations"][0]
