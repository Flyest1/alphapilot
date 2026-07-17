from __future__ import annotations

import re
from collections import Counter
from typing import Any, Mapping

from app.services.advisory.features.common import data_quality, evidence_item, now_iso

RISK_KEYWORDS = {
    "revenue_slowdown": ("revenue decline", "slower growth", "demand weakness"),
    "profitability": ("margin pressure", "operating loss", "impairment", "restructuring"),
    "debt_cash_flow": ("indebtedness", "debt covenant", "negative cash flow", "cash burn"),
    "liquidity": ("liquidity", "going concern", "substantial doubt", "working capital deficit"),
    "regulatory_litigation": ("litigation", "regulatory investigation", "subpoena", "penalty"),
    "customer_concentration": ("customer concentration", "major customer", "significant customer"),
    "supply_chain": ("supply chain", "sole source", "supplier concentration", "shortage"),
}

CAUTION_PHRASES = (
    "may adversely affect",
    "could materially affect",
    "substantial doubt",
    "uncertain",
    "cannot assure",
    "no assurance",
)
REQUIRED_FORMS = {"10-K", "10-Q", "8-K"}
SEC_ARCHIVES_URL_PREFIX = "https://www.sec.gov/Archives/"


class SECFilingRiskAnalyzer:
    def __init__(self, filing_provider: Any | None, now_provider: Any | None = None) -> None:
        self.filing_provider = filing_provider
        self.now_provider = now_provider

    def analyze(self, ticker: str) -> dict[str, Any]:
        filings = self._filings(ticker.upper())
        latest_by_form = self._latest_by_form(filings)
        generated_at = now_iso(self.now_provider)
        missing_forms = sorted(REQUIRED_FORMS - set(latest_by_form))
        missing_evidence = self._missing_evidence(latest_by_form)
        evaluation_available = not missing_forms and not missing_evidence
        category_findings = self._category_findings(latest_by_form)
        newly_emphasized = self._newly_emphasized(filings)
        cautious_signals = self._cautious_signals(latest_by_form)
        rating = self._rating(category_findings) if evaluation_available else "insufficient_data"
        rows = [
            {
                "category": category,
                "status": "identified" if finding["snippets"] else "not_identified",
                "snippets": finding["snippets"],
                "forms": finding["forms"],
            }
            for category, finding in category_findings.items()
        ]
        limitations = []
        if self.filing_provider is None:
            limitations.append("SEC EDGAR 제공자가 승인·설정되지 않았습니다.")
        if not filings:
            limitations.append("분석 가능한 10-K, 10-Q, 8-K 본문이 없습니다.")
        if missing_forms:
            limitations.append(f"필수 최신 공시가 누락되었습니다: {', '.join(missing_forms)}")
        if missing_evidence:
            limitations.append(
                "SEC filing evidence integrity is incomplete for the latest required filings: "
                f"{', '.join(missing_evidence)}."
            )
        if not evaluation_available:
            limitations.append("SEC filing evidence is unavailable; evaluation unavailable.")
        source_as_of = (
            max(
                (str(filing.get("filed_at") or "") for filing in latest_by_form.values()),
                default=None,
            )
            or None
        )
        return {
            "analysis_type": "sec_filing_risk",
            "generated_at": generated_at,
            "retrieved_at": generated_at,
            "source_as_of": source_as_of,
            "ticker": ticker.upper(),
            "latest_filings": [self._filing_summary(row) for row in latest_by_form.values()],
            "newly_emphasized_risks": newly_emphasized,
            "risk_categories": rows,
            "management_caution_signals": cautious_signals,
            "key_sentences": self._key_sentences(rows, cautious_signals),
            "risk_rating": rating,
            "evaluation_status": "available" if evaluation_available else "unavailable",
            "required_forms_complete": not missing_forms,
            "missing_forms": missing_forms,
            "missing_evidence": missing_evidence,
            "rating_reason": self._rating_reason(rating, rows),
            "evidence": self._evidence(latest_by_form),
            "data_quality": self._data_quality(
                rows, limitations, missing_evidence, evaluation_available
            ),
            "disclaimer": "공시 위험 분석은 법률·회계 자문이 아니며 원문 확인이 필요합니다.",
        }

    def _filings(self, ticker: str) -> list[dict[str, Any]]:
        if self.filing_provider is None:
            return []
        try:
            rows = self.filing_provider.list_recent_filings(ticker, ("10-K", "10-Q", "8-K"))
        except Exception:
            return []
        return [dict(row) for row in rows or [] if isinstance(row, Mapping)]

    @staticmethod
    def _latest_by_form(filings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result = {}
        for filing in sorted(filings, key=lambda row: str(row.get("filed_at") or ""), reverse=True):
            form = str(filing.get("form") or "")
            if form in {"10-K", "10-Q", "8-K"} and form not in result:
                result[form] = filing
        return result

    @staticmethod
    def _missing_evidence(filings: Mapping[str, Mapping[str, Any]]) -> list[str]:
        missing = []
        for form in sorted(REQUIRED_FORMS):
            filing = filings.get(form)
            if filing is None:
                continue
            if not str(filing.get("text") or "").strip():
                missing.append(f"{form}.text")
            if not str(filing.get("accession_number") or "").strip():
                missing.append(f"{form}.accession_number")
            if not SECFilingRiskAnalyzer._is_sec_archives_url(filing.get("url")):
                missing.append(f"{form}.url")
        return missing

    @staticmethod
    def _is_sec_archives_url(value: Any) -> bool:
        return isinstance(value, str) and value.strip().startswith(SEC_ARCHIVES_URL_PREFIX)

    @staticmethod
    def _data_quality(
        rows: list[dict[str, Any]],
        limitations: list[str],
        missing_evidence: list[str],
        evaluation_available: bool,
    ) -> dict[str, Any]:
        quality = data_quality(rows if evaluation_available else [], limitations)
        if missing_evidence:
            quality["missing_fields"] = missing_evidence
        return quality

    def _category_findings(
        self, filings: Mapping[str, Mapping[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        findings = {category: {"snippets": [], "forms": []} for category in RISK_KEYWORDS}
        for form, filing in filings.items():
            text = str(filing.get("text") or "")
            for category, keywords in RISK_KEYWORDS.items():
                snippets = self._snippets(text, keywords)
                if snippets:
                    findings[category]["snippets"].extend(snippets[:2])
                    findings[category]["forms"].append(form)
        return findings

    def _newly_emphasized(self, filings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for filing in filings:
            grouped.setdefault(str(filing.get("form") or ""), []).append(filing)
        changes = Counter()
        for rows in grouped.values():
            ordered = sorted(rows, key=lambda row: str(row.get("filed_at") or ""), reverse=True)
            if len(ordered) < 2:
                continue
            latest_text = str(ordered[0].get("text") or "").casefold()
            previous_text = str(ordered[1].get("text") or "").casefold()
            for category, keywords in RISK_KEYWORDS.items():
                delta = sum(
                    latest_text.count(word) - previous_text.count(word) for word in keywords
                )
                if delta > 0:
                    changes[category] += delta
        return [
            {"category": category, "mention_increase": count}
            for category, count in changes.most_common()
        ]

    def _cautious_signals(self, filings: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
        signals = []
        for form, filing in filings.items():
            for snippet in self._snippets(str(filing.get("text") or ""), CAUTION_PHRASES):
                signals.append({"form": form, "sentence": snippet})
        return signals[:10]

    @staticmethod
    def _snippets(text: str, phrases: tuple[str, ...]) -> list[str]:
        sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
        return [
            sentence[:500]
            for sentence in sentences
            if any(phrase in sentence.casefold() for phrase in phrases)
        ][:5]

    @staticmethod
    def _rating(findings: Mapping[str, Mapping[str, Any]]) -> str:
        identified = {key for key, value in findings.items() if value["snippets"]}
        severe = identified & {"liquidity", "debt_cash_flow", "regulatory_litigation"}
        if len(severe) >= 2 or len(identified) >= 5:
            return "high_risk"
        if len(identified) >= 2:
            return "caution"
        return "relative_low_risk"

    @staticmethod
    def _rating_reason(rating: str, rows: list[dict[str, Any]]) -> str:
        if rating == "insufficient_data":
            return "evaluation unavailable: SEC filing evidence is unavailable."
        categories = [row["category"] for row in rows if row["status"] == "identified"]
        if not categories:
            return "제공된 최신 공시에서 사전 정의된 핵심 위험 표현을 충분히 식별하지 못했습니다."
        return f"식별된 핵심 위험 범주: {', '.join(categories)}. 상대 평가 등급은 {rating}입니다."

    @staticmethod
    def _key_sentences(rows: list[dict[str, Any]], signals: list[dict[str, Any]]) -> list[str]:
        sentences = [snippet for row in rows for snippet in row["snippets"][:1]]
        sentences.extend(signal["sentence"] for signal in signals[:3])
        return list(dict.fromkeys(sentences))[:10]

    @staticmethod
    def _filing_summary(filing: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "form": filing.get("form"),
            "filed_at": filing.get("filed_at"),
            "accession_number": filing.get("accession_number"),
            "url": filing.get("url"),
        }

    @staticmethod
    def _evidence(filings: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [
            evidence_item(
                f"S{index}",
                "sec_edgar",
                f"{form} 공시",
                str(filing.get("filed_at") or "") or None,
                url=filing.get("url"),
            )
            for index, (form, filing) in enumerate(filings.items(), start=1)
        ]
