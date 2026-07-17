"""Read-only ETF underlying-overlap and exposure analysis."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from app.services.advisory.features import (
    finite_number,
    quality_summary,
    rounded,
    sector_weights_from_funds_data,
    target_weights,
    top_holdings_from_funds_data,
)

STYLE_BUCKETS = {
    "technology": {"QQQ", "VGT", "XLK", "IYW", "SOXX", "SMH"},
    "semiconductor": {"SOXX", "SMH", "XSD", "SOXQ"},
    "financial": {"XLF", "VFH", "KBE", "KRE"},
    "healthcare": {"XLV", "VHT", "IYH"},
    "dividend": {"SCHD", "VYM", "HDV", "DGRO", "SPYD", "SDY", "NOBL", "JEPI", "DIVO"},
    "growth": {"QQQ", "VUG", "IWF", "SCHG", "JEPQ"},
    "value": {"VTV", "IWD", "VYM", "HDV", "SCHD"},
}

SEMICONDUCTOR_HOLDINGS = {
    "AMD",
    "AMAT",
    "ASML",
    "AVGO",
    "INTC",
    "KLAC",
    "LRCX",
    "MU",
    "NVDA",
    "QCOM",
    "TSM",
    "TXN",
}


class EtfOverlapService:
    """Measure ETF top-10 overlap and approximate exposure without execution logic."""

    def __init__(self, yf_module: Any) -> None:
        self.yf_module = yf_module

    def analyze(self, positions: Sequence[Mapping[str, Any] | str]) -> dict[str, Any]:
        etfs = [self._analyze_position(position) for position in positions]
        weights_available = bool(etfs) and all(
            item["portfolio_weight_pct"] is not None for item in etfs
        )
        total_weight = sum(item["portfolio_weight_pct"] or 0 for item in etfs)
        normalized = weights_available and total_weight > 0
        holdings_coverage_available = bool(etfs) and all(item["top_holdings"] for item in etfs)
        corporate = self._corporate_exposure(etfs, total_weight) if normalized else []
        overlaps = self._pairwise_overlap(etfs)
        style = (
            self._style_exposure(etfs, total_weight) if normalized else self._empty_style_exposure()
        )
        requested_exposure = self._requested_exposure(etfs, corporate, style, total_weight)
        diversification = self._diversification_assessment(
            overlaps,
            corporate,
            normalized,
            holdings_coverage_available,
        )
        evidence = [item["evidence"] for item in etfs]
        return {
            "analysis_type": "etf_overlap",
            "etfs": etfs,
            "pairwise_overlap": overlaps,
            "actual_company_exposure": corporate,
            "style_exposure_approximation": style,
            "requested_exposure_summary": requested_exposure,
            "diversification_assessment": diversification,
            "portfolio_weight_status": "available" if normalized else "unavailable",
            "rebalancing_plans": self._plans(
                overlaps,
                corporate,
                normalized,
                holdings_coverage_available,
            ),
            "target_weight_scenarios": self._target_weight_scenarios(
                etfs,
                overlaps,
                normalized,
                total_weight,
            ),
            "data_quality": quality_summary(evidence),
            "evidence": evidence,
            "safety_note": (
                "중복은 각 ETF의 공개된 상위 10개 보유종목만으로 확인한 최소 중복입니다. "
                "전체 편입종목, 펀드 내 파생상품 및 미래 편입 변화는 포함하지 않습니다."
            ),
        }

    def _analyze_position(self, position: Mapping[str, Any] | str) -> dict[str, Any]:
        mapping = position if isinstance(position, Mapping) else {"ticker": position}
        ticker = str(mapping.get("ticker") or "").strip().upper()
        weight = finite_number(mapping.get("weight_pct"))
        try:
            fund = self.yf_module.Ticker(ticker)
            funds_data = getattr(fund, "funds_data", None)
            holdings, holdings_status = top_holdings_from_funds_data(
                funds_data,
                limit=10,
            )
            sectors, sectors_status = sector_weights_from_funds_data(funds_data)
        except Exception:
            holdings, holdings_status = [], "unavailable"
            sectors, sectors_status = [], "unavailable"
        evidence = {
            "ticker": ticker,
            "provider": "yfinance",
            "top_holdings_status": holdings_status,
            "sector_weights_status": sectors_status,
            "status": "available" if holdings_status == "available" else "limited",
        }
        return {
            "ticker": ticker,
            "portfolio_weight_pct": rounded(weight),
            "top_holdings": holdings,
            "sector_weights": sectors,
            "top10_coverage_pct": (
                rounded(sum(item["weight_pct"] for item in holdings)) if holdings else None
            ),
            "style_buckets": sorted(
                name for name, tickers in STYLE_BUCKETS.items() if ticker in tickers
            ),
            "evidence": evidence,
        }

    @staticmethod
    def _pairwise_overlap(etfs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for index, left in enumerate(etfs):
            left_weights = {item["ticker"]: item["weight_pct"] for item in left["top_holdings"]}
            for right in etfs[index + 1 :]:
                right_weights = {
                    item["ticker"]: item["weight_pct"] for item in right["top_holdings"]
                }
                common = sorted(set(left_weights) & set(right_weights))
                available = bool(left_weights) and bool(right_weights)
                overlap = (
                    rounded(sum(min(left_weights[key], right_weights[key]) for key in common))
                    if available
                    else None
                )
                rows.append(
                    {
                        "left_ticker": left["ticker"],
                        "right_ticker": right["ticker"],
                        "common_holdings": common if available else None,
                        "top10_overlap_pct": overlap,
                        "minimum_confirmed_overlap_pct": overlap,
                        "left_top10_coverage_pct": left["top10_coverage_pct"],
                        "right_top10_coverage_pct": right["top10_coverage_pct"],
                        "coverage_status": "available" if available else "data-limited",
                    }
                )
        return rows

    @staticmethod
    def _corporate_exposure(
        etfs: list[dict[str, Any]], total_weight: float
    ) -> list[dict[str, Any]]:
        exposure: defaultdict[str, float] = defaultdict(float)
        for etf in etfs:
            allocation = (etf["portfolio_weight_pct"] or 0) / total_weight
            for holding in etf["top_holdings"]:
                exposure[holding["ticker"]] += allocation * holding["weight_pct"]
        return [
            {"ticker": ticker, "portfolio_exposure_pct": rounded(weight)}
            for ticker, weight in sorted(exposure.items(), key=lambda item: item[1], reverse=True)
        ]

    @staticmethod
    def _style_exposure(etfs: list[dict[str, Any]], total_weight: float) -> dict[str, float]:
        exposure = {name: 0.0 for name in STYLE_BUCKETS}
        for etf in etfs:
            allocation = (etf["portfolio_weight_pct"] or 0) / total_weight * 100
            for bucket in etf["style_buckets"]:
                exposure[bucket] += allocation
        return {name: rounded(value) for name, value in exposure.items()}

    @staticmethod
    def _empty_style_exposure() -> dict[str, None]:
        return {name: None for name in STYLE_BUCKETS}

    @staticmethod
    def _requested_exposure(
        etfs: list[dict[str, Any]],
        corporate: list[dict[str, Any]],
        style: dict[str, float | None],
        total_weight: float,
    ) -> dict[str, Any]:
        if total_weight <= 0:
            return {
                "technology_pct": None,
                "semiconductor_minimum_confirmed_pct": None,
                "financial_pct": None,
                "healthcare_pct": None,
                "dividend_style_pct": None,
                "growth_style_pct": None,
                "value_style_pct": None,
                "status": "data-limited",
            }
        sector_totals: defaultdict[str, float] = defaultdict(float)
        for etf in etfs:
            portfolio_share = (etf["portfolio_weight_pct"] or 0.0) / total_weight
            for sector in etf["sector_weights"]:
                sector_totals[str(sector["sector"]).casefold()] += (
                    portfolio_share * sector["weight_pct"]
                )
        corporate_by_ticker = {item["ticker"]: item["portfolio_exposure_pct"] for item in corporate}
        semiconductor = sum(
            corporate_by_ticker.get(ticker, 0.0) for ticker in SEMICONDUCTOR_HOLDINGS
        )
        return {
            "technology_pct": rounded(
                sector_totals.get("technology", 0.0) + sector_totals.get("technology_services", 0.0)
            ),
            "semiconductor_minimum_confirmed_pct": rounded(semiconductor),
            "financial_pct": rounded(
                sector_totals.get("financial_services", 0.0) + sector_totals.get("financials", 0.0)
            ),
            "healthcare_pct": rounded(
                sector_totals.get("healthcare", 0.0) + sector_totals.get("health_care", 0.0)
            ),
            "dividend_style_pct": style.get("dividend"),
            "growth_style_pct": style.get("growth"),
            "value_style_pct": style.get("value"),
            "status": "available" if any(item["sector_weights"] for item in etfs) else "partial",
            "methodology": (
                "섹터는 ETF 공개 섹터 비중, 반도체는 공개 상위 10개 중 확인된 기업만 반영합니다."
            ),
        }

    @staticmethod
    def _diversification_assessment(
        overlaps: list[dict[str, Any]],
        corporate: list[dict[str, Any]],
        weights_available: bool,
        holdings_coverage_available: bool,
    ) -> dict[str, Any]:
        if not weights_available or not holdings_coverage_available:
            return {
                "status": "data-limited",
                "level": None,
                "largest_company_exposure_pct": None,
                "maximum_pairwise_top10_overlap_pct": None,
                "reason": (
                    "포트폴리오 비중 또는 보유종목 coverage가 없어 분산 수준을 계산할 수 없습니다."
                ),
            }
        max_overlap = max(
            (item["minimum_confirmed_overlap_pct"] or 0.0 for item in overlaps),
            default=0.0,
        )
        max_company = corporate[0]["portfolio_exposure_pct"] if corporate else 0.0
        if max_company >= 20 or max_overlap >= 50:
            level = "concentrated"
        elif max_company >= 10 or max_overlap >= 25:
            level = "moderate"
        else:
            level = "diversified_within_observed_top10"
        return {
            "status": "available",
            "level": level,
            "largest_company_exposure_pct": max_company,
            "maximum_pairwise_top10_overlap_pct": max_overlap,
            "reason": "공개 상위 10개 보유종목 범위에서만 평가한 최소 확인 분산 수준입니다.",
        }

    @staticmethod
    def _plans(
        overlaps: list[dict[str, Any]],
        corporate: list[dict[str, Any]],
        weights_available: bool,
        holdings_coverage_available: bool,
    ) -> list[dict[str, Any]]:
        if not weights_available or not holdings_coverage_available:
            return [
                {
                    "name": "concentration_reduction",
                    "condition": None,
                    "guidance": "보유종목 coverage가 없어 집중도 조정안을 만들지 않습니다.",
                    "status": "data-limited",
                },
                {
                    "name": "core_satellite",
                    "condition": None,
                    "guidance": "보유종목 coverage가 없어 코어·위성 조정안을 만들지 않습니다.",
                    "status": "data-limited",
                },
                {
                    "name": "income_growth_balance",
                    "condition": None,
                    "guidance": "보유종목 coverage가 없어 배당·성장 조정안을 만들지 않습니다.",
                    "status": "data-limited",
                },
            ]
        max_overlap = max((item["top10_overlap_pct"] or 0 for item in overlaps), default=0)
        max_company = corporate[0]["portfolio_exposure_pct"] if corporate else None
        return [
            {
                "name": "concentration_reduction",
                "condition": (
                    f"top-10 overlap {max_overlap}% or single-company exposure {max_company}%"
                ),
                "guidance": "공개 상위 10개 보유종목의 중복과 단일 기업 노출을 함께 검토합니다.",
                "status": "available",
            },
            {
                "name": "core_satellite",
                "condition": "broad core and sector satellite exposures are identifiable",
                "guidance": "스타일 분류는 알려진 ETF 티커 범주에 한정된 근사치입니다.",
                "status": "available",
            },
            {
                "name": "income_growth_balance",
                "condition": "dividend and growth buckets are both represented",
                "guidance": "배당·성장 스타일 노출은 ETF 전체 편입종목 분석이 아닙니다.",
                "status": "available",
            },
        ]

    @staticmethod
    def _target_weight_scenarios(
        etfs: list[dict[str, Any]],
        overlaps: list[dict[str, Any]],
        weights_available: bool,
        total_weight: float,
    ) -> list[dict[str, Any]]:
        current_targets = (
            target_weights([(item["ticker"], item["portfolio_weight_pct"] or 0.0) for item in etfs])
            if weights_available and total_weight > 0
            else []
        )
        equal_targets = target_weights([(item["ticker"], 1.0) for item in etfs])
        overlap_by_ticker: defaultdict[str, float] = defaultdict(float)
        coverage_by_ticker = {item["ticker"]: bool(item["top_holdings"]) for item in etfs}
        for row in overlaps:
            overlap = finite_number(row["minimum_confirmed_overlap_pct"])
            if overlap is not None:
                overlap_by_ticker[row["left_ticker"]] += overlap
                overlap_by_ticker[row["right_ticker"]] += overlap
        overlap_scores = [
            (item["ticker"], max(1.0, 100.0 - overlap_by_ticker[item["ticker"]]))
            for item in etfs
            if coverage_by_ticker[item["ticker"]]
        ]
        overlap_targets = target_weights(overlap_scores) if len(overlap_scores) == len(etfs) else []
        return [
            {
                "name": "current_weight_reference",
                "target_weights": current_targets,
                "status": "available" if current_targets else "data-limited",
                "basis": (
                    "entered portfolio weights normalized to 100%; no recommendation is implied"
                ),
            },
            {
                "name": "equal_weight_reference",
                "target_weights": equal_targets,
                "status": "available" if equal_targets else "data-limited",
                "basis": (
                    "equal ETF weights for comparison only; holdings overlap is not considered"
                ),
            },
            {
                "name": "top10_overlap_aware_reference",
                "target_weights": overlap_targets,
                "status": "available" if overlap_targets else "data-limited",
                "basis": (
                    "weights are inversely related to confirmed pairwise top-10 overlap; "
                    "this is not a complete holdings-based optimization"
                ),
            },
        ]
