from __future__ import annotations

from typing import Any, Mapping

from app.services.advisory.features.common import (
    data_quality,
    evidence_item,
    finite_float,
    now_iso,
    period_return,
    rounded,
    ticker_snapshot,
)

CRITERIA = {
    "revenue_contribution": ("ai revenue", "ai-related revenue", "revenue from ai"),
    "product_or_service": ("ai product", "ai service", "generative ai", "ai platform"),
    "specific_disclosure": ("contract", "customer", "deployment", "usage"),
    "cost_reduction": ("cost reduction", "productivity", "automation", "efficiency"),
    "customer_or_contract_growth": ("new customer", "contract growth", "bookings", "backlog"),
    "differentiation": ("proprietary", "patent", "specialized model", "inference platform"),
}


class AIBeneficiariesAnalyzer:
    def __init__(
        self,
        market_data_service: Any,
        yf_module: Any,
        disclosure_provider: Any | None = None,
        now_provider: Any | None = None,
    ) -> None:
        self.market_data_service = market_data_service
        self.yf_module = yf_module
        self.disclosure_provider = disclosure_provider
        self.now_provider = now_provider

    def analyze(self, tickers: list[str]) -> dict[str, Any]:
        generated_at = now_iso(self.now_provider)
        rows = [
            self._analyze_ticker(ticker.upper(), generated_at) for ticker in dict.fromkeys(tickers)
        ]
        verified = sorted(
            [
                row
                for row in rows
                if row["classification"] == "verified_ai_beneficiary"
                and row["analysis_status"] == "available"
            ],
            key=lambda row: (-row["investment_appeal_10"], row["ticker"]),
        )[:10]
        caution = sorted(
            [row for row in rows if row["classification"] == "ai_theme_caution"],
            key=self._caution_sort_key,
        )[:5]
        limitations = []
        if self.disclosure_provider is None:
            limitations.append(
                "공식 공시 기반 AI 매출·계약 근거 제공자가 없어 모든 종목을 테마 주의로 분류합니다."
            )
        if any(row["analysis_status"] == "data-limited" for row in rows):
            limitations.append("Required AI disclosure or market evidence is unavailable.")
        return {
            "analysis_type": "ai_beneficiaries",
            "generated_at": generated_at,
            "verified_ai_beneficiaries": verified,
            "ai_theme_caution": caution,
            "rows": rows,
            "evidence": self._evidence(rows),
            "data_quality": data_quality(rows, limitations),
            "disclaimer": "AI 관련 표현만으로 실질적인 수혜를 단정하지 않습니다.",
        }

    def _analyze_ticker(self, ticker: str, retrieved_at: str | None = None) -> dict[str, Any]:
        snapshot = ticker_snapshot(self.yf_module, ticker)
        info = snapshot["info"]
        market_data = self.market_data_service.fetch_price_history("US", ticker, 220)
        disclosures = self._disclosures(ticker)
        disclosure_evidence = self._disclosure_evidence(disclosures)
        combined_text = " ".join(str(row.get("text") or "") for row in disclosures).casefold()
        criteria = {
            name: any(keyword in combined_text for keyword in keywords)
            for name, keywords in CRITERIA.items()
        }
        quantitative_count = sum(
            bool(row.get("metrics")) and isinstance(row.get("metrics"), Mapping)
            for row in disclosures
        )
        evidence_count = sum(criteria.values())
        verified = evidence_count >= 4 and quantitative_count > 0
        forward_pe = finite_float(info.get("forwardPE"))
        six_month_return = period_return(market_data, 132)
        analysis_available = (
            verified
            and six_month_return is not None
            and not bool(getattr(market_data, "is_stale", True))
            and getattr(market_data, "last_trading_date", None) is not None
        )
        if analysis_available:
            overheating = 2.0
            if forward_pe is not None:
                overheating += min(max((forward_pe - 20) / 7, 0), 4)
            overheating += min(max(six_month_return / 20, 0), 4)
            long_term = min(10.0, 2.0 + evidence_count * 1.2 + quantitative_count)
            appeal = min(10.0, long_term * 0.7 + (10 - overheating) * 0.3)
        else:
            overheating = None
            long_term = None
            appeal = None
        action = "BUY" if appeal is not None and appeal >= 6 else "WATCH"
        source_as_of = next((row.get("as_of") for row in disclosures if row.get("as_of")), None)
        return {
            "ticker": ticker,
            "name": info.get("longName") or ticker,
            "classification": "verified_ai_beneficiary" if verified else "ai_theme_caution",
            "criteria": criteria,
            "quantitative_evidence_count": quantitative_count,
            "disclosure_count": len(disclosures),
            "forward_pe": rounded(forward_pe),
            "six_month_return_pct": six_month_return,
            "investment_appeal_10": round(appeal, 1) if appeal is not None else None,
            "overheating_risk_10": (
                round(min(overheating, 10), 1) if overheating is not None else None
            ),
            "long_term_growth_10": round(long_term, 1) if long_term is not None else None,
            "action": action,
            "analysis_status": "available" if analysis_available else "data-limited",
            "data_quality_status": "fresh" if analysis_available else "data-limited",
            "source_urls": [row.get("url") for row in disclosures if row.get("url")],
            "disclosure_evidence": disclosure_evidence,
            "as_of": source_as_of,
            "source_as_of": source_as_of,
            "retrieved_at": retrieved_at or now_iso(self.now_provider),
        }

    @staticmethod
    def _caution_sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
        risk_score = finite_float(row.get("overheating_risk_10"))
        if row.get("analysis_status") == "available" and risk_score is not None:
            return (0, -risk_score, row["ticker"])
        if row.get("analysis_status") == "available":
            return (1, 0.0, row["ticker"])
        return (2, 0.0, row["ticker"])

    def _disclosures(self, ticker: str) -> list[dict[str, Any]]:
        if self.disclosure_provider is None:
            return []
        try:
            rows = self.disclosure_provider.get_ai_disclosures(ticker)
        except Exception:
            return []
        return [dict(row) for row in rows or [] if isinstance(row, Mapping)]

    @staticmethod
    def _disclosure_evidence(disclosures: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        all_keywords = {keyword for keywords in CRITERIA.values() for keyword in keywords}
        for disclosure in disclosures:
            text = " ".join(str(disclosure.get("text") or "").split())
            matched_criteria = [
                name
                for name, keywords in CRITERIA.items()
                if any(keyword in text.casefold() for keyword in keywords)
            ]
            sentences = [
                sentence.strip()[:500]
                for sentence in text.replace("!", ".").replace("?", ".").split(".")
                if any(keyword in sentence.casefold() for keyword in all_keywords)
            ][:3]
            rows.append(
                {
                    "form": disclosure.get("form"),
                    "as_of": disclosure.get("as_of") or disclosure.get("filed_at"),
                    "accession_number": disclosure.get("accession_number"),
                    "url": disclosure.get("url"),
                    "matched_criteria": matched_criteria,
                    "metrics": dict(disclosure.get("metrics") or {}),
                    "supporting_sentences": sentences,
                }
            )
        return rows

    @staticmethod
    def _evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        evidence = []
        for row_index, row in enumerate(rows, start=1):
            disclosures = row.get("disclosure_evidence") or []
            if not disclosures:
                evidence.append(
                    evidence_item(
                        f"A{row_index}",
                        "yfinance",
                        f"{row['ticker']} AI 수혜 근거",
                        row.get("as_of"),
                        limitations=["공식 AI 정량 근거를 확인하지 못했습니다."],
                    )
                )
                continue
            for disclosure_index, disclosure in enumerate(disclosures, start=1):
                evidence.append(
                    evidence_item(
                        f"A{row_index}-{disclosure_index}",
                        "official_disclosure",
                        f"{row['ticker']} {disclosure.get('form') or '공시'} AI 근거",
                        disclosure.get("as_of"),
                        url=disclosure.get("url"),
                    )
                )
        return evidence
