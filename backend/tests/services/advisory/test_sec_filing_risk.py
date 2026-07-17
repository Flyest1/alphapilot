from app.services.advisory.features.sec_filing_risk import SECFilingRiskAnalyzer


class FakeSECProvider:
    def list_recent_filings(self, _ticker, forms):
        assert forms == ("10-K", "10-Q", "8-K")
        return [
            {
                "form": "10-Q",
                "filed_at": "2026-06-01",
                "accession_number": "0001",
                "url": "https://example.test/10q-new",
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
                "url": "https://example.test/10q-old",
                "text": "We face supply chain risk.",
            },
            {
                "form": "10-K",
                "filed_at": "2026-02-01",
                "accession_number": "k001",
                "url": "https://example.test/10k",
                "text": "Customer concentration may adversely affect revenue.",
            },
            {
                "form": "8-K",
                "filed_at": "2026-06-10",
                "accession_number": "8k01",
                "url": "https://example.test/8k",
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
