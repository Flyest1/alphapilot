from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from app.models.advisory import AdvisoryJobRequest
from app.services.advisory.features.ai_beneficiaries import AIBeneficiariesAnalyzer
from app.services.advisory.features.etf_overlap import EtfOverlapService
from app.services.advisory.features.etf_rebalancing import EtfRebalancingService
from app.services.advisory.features.high_dividend_etfs import HighDividendEtfService
from app.services.advisory.features.post_earnings_opportunities import (
    PostEarningsOpportunitiesAnalyzer,
)
from app.services.advisory.features.sec_filing_risk import SECFilingRiskAnalyzer
from app.services.advisory.features.sector_outlook import SectorOutlookService
from app.services.advisory.features.undervalued_us_stocks import UndervaluedUSStocksAnalyzer
from app.services.advisory.openai_provider import OpenAIAdvisoryProvider
from app.services.portfolio_service import PortfolioService
from app.utils.logging import log_external_failure


class AdvisoryPipeline:
    def __init__(
        self,
        repository: Any,
        market_data_service: Any,
        yf_module: Any | None = None,
        filing_provider: Any | None = None,
        macro_provider: Any | None = None,
        news_service: Any | None = None,
        narrative_provider: OpenAIAdvisoryProvider | None = None,
    ) -> None:
        self.repository = repository
        self.market_data_service = market_data_service
        self.yf_module = yf_module
        self.filing_provider = filing_provider
        self.macro_provider = macro_provider
        self.news_service = news_service
        self.narrative_provider = narrative_provider

    def handlers(self) -> Mapping[str, Callable[[Any, AdvisoryJobRequest], dict[str, Any]]]:
        return {
            "undervalued_us_stocks": self._undervalued_us_stocks,
            "etf_rebalancing": self._etf_rebalancing,
            "post_earnings_opportunities": self._post_earnings_opportunities,
            "ai_beneficiaries": self._ai_beneficiaries,
            "high_dividend_etfs": self._high_dividend_etfs,
            "sec_filing_risk": self._sec_filing_risk,
            "etf_overlap": self._etf_overlap,
            "sector_outlook": self._sector_outlook,
        }

    def _undervalued_us_stocks(self, _job: Any, request: Any) -> dict[str, Any]:
        tickers = self._equity_tickers(getattr(request, "tickers", []))
        result = UndervaluedUSStocksAnalyzer(
            self.market_data_service,
            self._yf_module(),
            filing_provider=self.filing_provider,
        ).analyze(
            tickers,
            limit=getattr(request, "max_results", 5),
            min_market_cap_usd=getattr(request, "min_market_cap_usd", None),
        )
        self._attach_news_context(result, tickers)
        return self._add_narrative(result)

    def _etf_rebalancing(self, _job: Any, request: Any) -> dict[str, Any]:
        positions = self._positions(request)
        result = EtfRebalancingService(
            self.market_data_service,
            self._yf_module(),
        ).analyze(positions)
        result["input_positions"] = positions
        return self._add_narrative(result)

    def _post_earnings_opportunities(self, _job: Any, request: Any) -> dict[str, Any]:
        tickers = self._equity_tickers(getattr(request, "tickers", []))
        result = PostEarningsOpportunitiesAnalyzer(
            self.market_data_service,
            self._yf_module(),
            filing_provider=self.filing_provider,
        ).analyze(
            tickers,
            limit=getattr(request, "max_results", 5),
            lookback_days=getattr(request, "lookback_days", 14),
        )
        self._attach_news_context(result, tickers)
        return self._add_narrative(result)

    def _ai_beneficiaries(self, _job: Any, request: Any) -> dict[str, Any]:
        tickers = self._equity_tickers(getattr(request, "tickers", []))
        result = AIBeneficiariesAnalyzer(
            self.market_data_service,
            self._yf_module(),
            disclosure_provider=self.filing_provider,
        ).analyze(tickers)
        self._attach_news_context(result, tickers)
        return self._add_narrative(result)

    def _high_dividend_etfs(self, _job: Any, request: Any) -> dict[str, Any]:
        requested = [str(value).upper() for value in getattr(request, "tickers", [])]
        service = HighDividendEtfService(self.market_data_service, self._yf_module())
        minimum_yield = getattr(request, "min_distribution_yield_percent", None)
        result = (
            service.analyze(requested, min_distribution_yield_percent=minimum_yield)
            if requested
            else service.analyze(min_distribution_yield_percent=minimum_yield)
        )
        return self._add_narrative(result)

    def _sec_filing_risk(self, _job: Any, request: Any) -> dict[str, Any]:
        ticker = str(getattr(request, "ticker", "") or "").upper()
        if not ticker:
            tickers = getattr(request, "tickers", [])
            ticker = str(tickers[0] if tickers else "").upper()
        result = SECFilingRiskAnalyzer(self.filing_provider).analyze(ticker)
        return self._add_narrative(result)

    def _etf_overlap(self, _job: Any, request: Any) -> dict[str, Any]:
        positions = self._positions(request)
        result = EtfOverlapService(self._yf_module()).analyze(positions)
        return self._add_narrative(result)

    def _sector_outlook(self, _job: Any, request: Any) -> dict[str, Any]:
        proxies = getattr(request, "custom_proxies", None)
        service = SectorOutlookService(
            self.market_data_service,
            self._yf_module(),
            macro_provider=self.macro_provider,
            fund_flow_provider=self.filing_provider,
        )
        result = service.analyze(proxies=proxies) if proxies else service.analyze()
        self._attach_news_context(result, [])
        result["market_input_coverage"] = self._sector_market_input_coverage(result)
        return self._add_narrative(result)

    def _positions(self, request: Any) -> list[dict[str, Any]]:
        raw_positions = getattr(request, "positions", None)
        if raw_positions:
            positions = [
                {
                    "ticker": str(position.ticker).upper(),
                    "weight_pct": getattr(position, "weight_pct", None),
                }
                for position in raw_positions
            ]
            return self._fill_missing_weights(positions)
        legacy_tickers = getattr(request, "etf_tickers", None)
        if legacy_tickers:
            return [
                {"ticker": str(ticker).upper(), "weight_pct": None} for ticker in legacy_tickers
            ]
        assets = [row for row in self.repository.list_assets() if row.get("market") == "ETF"]
        try:
            summary = PortfolioService(self.repository, self.market_data_service).get_summary()
            allocations = [
                row
                for row in summary.asset_allocation
                if row.get("market") == "ETF" and row.get("ticker")
            ]
            etf_total = sum(float(row.get("market_value") or 0.0) for row in allocations)
            if allocations and etf_total > 0:
                return [
                    {
                        "ticker": str(row["ticker"]).upper(),
                        "weight_pct": round(
                            float(row.get("market_value") or 0.0) / etf_total * 100,
                            2,
                        ),
                    }
                    for row in allocations
                ]
        except Exception as exc:
            log_external_failure(
                "portfolio",
                exc,
                {"operation": "resolve_advisory_etf_weights"},
            )
        return [
            {"ticker": str(row.get("ticker") or "").upper(), "weight_pct": None}
            for row in assets
            if row.get("ticker")
        ]

    @staticmethod
    def _fill_missing_weights(positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        missing_indices = [
            index for index, row in enumerate(positions) if row.get("weight_pct") is None
        ]
        if not missing_indices:
            return positions
        specified_total = sum(
            float(row.get("weight_pct") or 0.0)
            for row in positions
            if row.get("weight_pct") is not None
        )
        if specified_total > 100:
            return positions
        remaining = max(100.0 - specified_total, 0.0)
        allocated = 0.0
        for offset, index in enumerate(missing_indices):
            weight = remaining - allocated
            if offset < len(missing_indices) - 1:
                weight = round(remaining / len(missing_indices), 2)
                allocated += weight
            positions[index]["weight_pct"] = round(weight, 2)
        return positions

    def _equity_tickers(self, requested: list[str]) -> list[str]:
        if requested:
            return [str(ticker).upper() for ticker in dict.fromkeys(requested)]
        rows = self.repository.list_candidate_universe("global")
        return [
            str(row.get("ticker") or "").upper()
            for row in rows
            if row.get("market") == "US" and row.get("ticker")
        ]

    def _yf_module(self) -> Any:
        if self.yf_module is not None:
            return self.yf_module
        return self.market_data_service._yf_module()

    def _add_narrative(self, result: dict[str, Any]) -> dict[str, Any]:
        self._prepare_result(result)
        if not result.get("evidence"):
            result["ai_narrative"] = None
            result["ai_narrative_status"] = {
                "status": "unavailable",
                "reason": "no_evidence",
                "provider": "openai",
            }
            result.setdefault("data_quality", {}).setdefault("limitations", []).append(
                "인용 가능한 근거가 없어 AI 설명을 생성하지 않았습니다."
            )
            return result
        if self.narrative_provider is None:
            result["ai_narrative"] = None
            result["ai_narrative_status"] = {
                "status": "unavailable",
                "reason": "not_configured",
                "provider": "openai",
            }
            result.setdefault("data_quality", {}).setdefault("limitations", []).append(
                "AI 설명을 사용할 수 없어 결정론적 분석만 제공합니다."
            )
            return result
        try:
            narrative = self.narrative_provider.generate_narrative(
                str(result.get("analysis_type") or "advisory"),
                result,
            )
            result["ai_narrative"] = narrative.model_dump(mode="json")
            result["ai_narrative_status"] = {
                "status": "available",
                "reason": None,
                "provider": "openai",
            }
        except Exception as exc:
            log_external_failure(
                "advisory_narrative",
                exc,
                {"analysis_type": result.get("analysis_type")},
            )
            result["ai_narrative"] = None
            result["ai_narrative_status"] = {
                "status": "unavailable",
                "reason": "generation_failed",
                "provider": "openai",
            }
            result.setdefault("data_quality", {}).setdefault("limitations", []).append(
                "AI 설명 생성에 실패하여 결정론적 분석만 제공합니다."
            )
        return result

    def _attach_news_context(self, result: dict[str, Any], tickers: list[str]) -> None:
        if self.news_service is None:
            result["news_context"] = {
                "provider": "gdelt_doc_2_0",
                "status": "unavailable",
                "articles": [],
            }
            result.setdefault("data_quality", {}).setdefault("limitations", []).append(
                "최근 뉴스 근거를 수집하지 못했습니다."
            )
            return
        assets = [{"ticker": ticker, "name": ticker, "market": "US"} for ticker in tickers[:3]]
        try:
            try:
                context = self.news_service.fetch_report_context(
                    "global",
                    assets,
                    max_queries=1,
                )
            except TypeError:
                context = self.news_service.fetch_report_context("global", assets)
        except Exception as exc:
            log_external_failure("gdelt", exc, {"operation": "advisory_news_context"})
            context = {
                "provider": "gdelt_doc_2_0",
                "status": "unavailable",
                "articles": [],
            }
        result["news_context"] = context
        evidence = result.setdefault("evidence", [])
        for article in context.get("articles", []):
            if not isinstance(article, dict):
                continue
            evidence.append(
                {
                    "provider": "gdelt_doc_2_0",
                    "title": article.get("title") or "최근 뉴스",
                    "url": article.get("url"),
                    "as_of": article.get("published_at") or article.get("seendate"),
                    "scope": article.get("scope"),
                    "asset_ticker": article.get("asset_ticker"),
                    "limitations": ["최근 뉴스·동향 문맥이며 기업 공식 공시를 대체하지 않습니다."],
                }
            )

    @staticmethod
    def _sector_market_input_coverage(result: dict[str, Any]) -> dict[str, Any]:
        news_context = result.get("news_context") or {}
        sector_rows = result.get("sectors") or []
        price_status = (
            "available"
            if sector_rows and all(row.get("data_quality") == "fresh" for row in sector_rows)
            else "partial"
        )
        unavailable_note = "구조화 데이터를 수집하지 못해 현재 data-limited입니다."
        macro_context = result.get("macro_context") or {}
        macro_series = macro_context.get("series") or []
        macro_categories = {
            str(row.get("category"))
            for row in macro_series
            if isinstance(row, dict) and row.get("category")
        }
        flow_contexts = [
            row.get("etf_flow_context")
            for row in sector_rows
            if isinstance(row.get("etf_flow_context"), dict)
        ]
        actual_flow_count = sum(
            context.get("provider") == "sec_edgar_nport"
            and context.get("status") in {"available", "data_limited"}
            for context in flow_contexts
        )
        proxy_flow_count = sum(
            context.get("provider") == "yfinance_price_volume_proxy"
            and context.get("status") == "proxy"
            for context in flow_contexts
        )
        fundamentals = [
            row.get("fundamentals")
            for row in sector_rows
            if isinstance(row.get("fundamentals"), dict)
        ]

        def coverage_status(*fields: str) -> str:
            available = sum(
                any(item.get(field) is not None for field in fields) for item in fundamentals
            )
            if not fundamentals or available == 0:
                return "data-limited"
            return "available" if available == len(fundamentals) else "partial"

        return {
            "price_trend": {"status": price_status, "provider": "yfinance"},
            "interest_rate_outlook": {
                "status": (
                    "available"
                    if {"policy_rate", "treasury_yield"} & macro_categories
                    else "data-limited"
                ),
                "provider": "fred",
                "note": "관측값이며 미래 금리 예측이 아닙니다.",
            },
            "inflation": {
                "status": "available" if "inflation" in macro_categories else "data-limited",
                "provider": "fred",
                "note": "공개된 관측값이며 미래 인플레이션 예측이 아닙니다.",
            },
            "corporate_earnings": {
                "status": coverage_status("earnings_growth_pct", "revenue_growth_pct"),
                "provider": "yfinance",
            },
            "eps_growth": {
                "status": coverage_status("earnings_growth_pct"),
                "provider": "yfinance",
            },
            "valuation": {
                "status": coverage_status("trailing_pe", "forward_pe", "price_to_book"),
                "provider": "yfinance",
            },
            "capital_flows": {
                "status": (
                    "available"
                    if actual_flow_count
                    else ("proxy" if proxy_flow_count else "data-limited")
                ),
                "provider": (
                    "sec_edgar_nport" if actual_flow_count else "yfinance_price_volume_proxy"
                ),
                "note": (
                    "N-PORT는 지연 공개 자료이며 yfinance 값은 가격·거래량 프록시입니다."
                    if actual_flow_count or proxy_flow_count
                    else unavailable_note
                ),
            },
            "recent_news": {
                "status": news_context.get("status") or "unavailable",
                "provider": news_context.get("provider") or "gdelt_doc_2_0",
                "article_count": len(news_context.get("articles") or []),
            },
            "etf_flows": {
                "status": (
                    "available"
                    if actual_flow_count
                    else ("proxy" if proxy_flow_count else "data-limited")
                ),
                "provider": (
                    "sec_edgar_nport" if actual_flow_count else "yfinance_price_volume_proxy"
                ),
                "actual_nport_count": actual_flow_count,
                "proxy_count": proxy_flow_count,
                "note": (
                    "N-PORT는 지연 공개 자료이며 프록시는 실제 순유입·순유출이 아닙니다."
                    if actual_flow_count or proxy_flow_count
                    else unavailable_note
                ),
            },
        }

    @staticmethod
    def _prepare_result(result: dict[str, Any]) -> None:
        analysis_type = str(result.get("analysis_type") or "advisory")
        retrieved_at = datetime.now(timezone.utc).isoformat()
        result.setdefault("retrieved_at", retrieved_at)
        result.setdefault(
            "disclaimer",
            "투자 의사결정 지원 정보이며 수익을 보장하지 않습니다. "
            "자동매매나 주문을 실행하지 않습니다.",
        )
        evidence = result.get("evidence")
        if not isinstance(evidence, list):
            evidence = []
            result["evidence"] = evidence
        providers: set[str] = set()
        as_of_values: list[str] = []
        evidence_ids: set[str] = set()
        for index, item in enumerate(evidence, start=1):
            if not isinstance(item, dict):
                continue
            provider = str(item.get("provider") or "unknown").strip() or "unknown"
            item["provider"] = provider
            providers.add(provider)
            evidence_id = str(item.get("evidence_id") or "").strip()
            if not evidence_id or evidence_id in evidence_ids:
                evidence_id = f"{analysis_type}:{provider}:{index}"
            item["evidence_id"] = evidence_id
            evidence_ids.add(evidence_id)
            item.setdefault("retrieved_at", retrieved_at)
            as_of = item.get("as_of") or item.get("last_trading_date")
            if as_of:
                item["as_of"] = str(as_of)
                as_of_values.append(str(as_of))
        quality = result.setdefault("data_quality", {})
        if isinstance(quality, dict):
            quality.setdefault("providers", sorted(providers))
            quality.setdefault("retrieved_at", retrieved_at)
            quality.setdefault("source_as_of", max(as_of_values) if as_of_values else None)
