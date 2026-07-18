"""Read-only ETF comparison and scenario rebalancing analysis."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from app.services.advisory.features import (
    annualized_volatility,
    close_series,
    dividends_from_ticker,
    finite_number,
    period_return,
    quality_summary,
    rounded,
    sector_weights_from_funds_data,
    target_weights,
    top_holdings_from_funds_data,
)
from app.services.market_data_service import MarketDataService

RATE_SENSITIVE_TICKERS = {"TLT", "IEF", "AGG", "BND", "VNQ", "IYR", "XLRE", "QQQ", "VUG"}
RECESSION_RESILIENT_TICKERS = {"XLP", "XLV", "XLU", "VDC", "VHT", "VPU", "SCHD", "VYM", "HDV"}


class EtfRebalancingService:
    """Build deterministic scenarios from observable ETF market and fund data."""

    def __init__(self, market_data_service: MarketDataService, yf_module: Any) -> None:
        self.market_data_service = market_data_service
        self.yf_module = yf_module

    def analyze(
        self,
        positions: Sequence[Mapping[str, Any] | str],
        stale_data_business_days: int = 2,
    ) -> dict[str, Any]:
        normalized_positions = [self._normalize_position(position) for position in positions]
        etfs = [
            self._analyze_etf(position, stale_data_business_days)
            for position in normalized_positions
        ]
        evidence = [item["evidence"] for item in etfs]
        overlap = self._pairwise_overlap(etfs)
        current_weight_metadata = self._current_weight_metadata(etfs)
        return {
            "analysis_type": "etf_rebalancing",
            "etfs": etfs,
            "current_weight_metadata": current_weight_metadata,
            "top10_overlap": overlap,
            "scenarios": self._scenarios(etfs, current_weight_metadata),
            "data_quality": quality_summary(evidence),
            "evidence": evidence,
            "disclaimer": (
                "참고용 분석이며 자동 매매, 주문 수량, 수익 보장을 제공하지 않습니다. "
                "상위 10개 보유종목 기준 중복은 ETF 전체 편입종목의 중복을 뜻하지 않습니다."
            ),
        }

    @staticmethod
    def _normalize_position(position: Mapping[str, Any] | str) -> dict[str, Any]:
        mapping = position if isinstance(position, Mapping) else {"ticker": position}
        return {
            "ticker": str(mapping.get("ticker") or "").strip().upper(),
            "current_weight_pct": rounded(finite_number(mapping.get("weight_pct"))),
        }

    def _analyze_etf(
        self,
        position: Mapping[str, Any],
        stale_data_business_days: int,
    ) -> dict[str, Any]:
        symbol = str(position["ticker"])
        market_data = self.market_data_service.fetch_price_history(
            "ETF", symbol, lookback_days=1_100, stale_data_business_days=stale_data_business_days
        )
        close = close_series(market_data.dataframe)
        fund, metadata_status = self._fund_metadata(symbol)
        funds_data = self._funds_data(fund)
        adjusted_close = self._adjusted_close(fund)
        current_price = finite_number(market_data.current_price)
        distributions = dividends_from_ticker(fund) if fund is not None else close.iloc[0:0]
        trailing_yield = (
            self._trailing_yield(distributions, close, current_price)
            if not market_data.is_stale
            else None
        )
        holdings, holdings_status = top_holdings_from_funds_data(funds_data)
        sectors, sectors_status = sector_weights_from_funds_data(funds_data)
        market_available = not close.empty and not market_data.is_stale
        required_sources_available = (
            not adjusted_close.empty
            and holdings_status == "available"
            and sectors_status == "available"
        )
        status = (
            "available"
            if market_available and required_sources_available
            else "partial" if market_available else "limited"
        )
        evidence = {
            "ticker": symbol,
            "provider": market_data.provider,
            "last_trading_date": (
                market_data.last_trading_date.isoformat() if market_data.last_trading_date else None
            ),
            "market_data_note": market_data.data_quality_note,
            "metadata_status": metadata_status,
            "adjusted_total_return_status": (
                "available" if not adjusted_close.empty else "unavailable"
            ),
            "holdings_status": holdings_status,
            "sector_status": sectors_status,
            "status": status,
        }
        return {
            "ticker": symbol,
            "current_weight_pct": position["current_weight_pct"],
            "metrics": {
                "return_1y_pct": rounded(period_return(adjusted_close, 252)),
                "return_3y_pct": rounded(period_return(adjusted_close, 756)),
                "return_basis": "distribution-adjusted total return",
                "annualized_volatility_pct": rounded(annualized_volatility(adjusted_close)),
                "trailing_distribution_yield_pct": rounded(trailing_yield),
            },
            "top_holdings": holdings,
            "sector_weights": sectors,
            "sensitivity": self._sensitivity(symbol),
            "data_quality": (
                "fresh"
                if status == "available"
                else "partial" if status == "partial" else "data-limited"
            ),
            "evidence": evidence,
        }

    @staticmethod
    def _current_weight_metadata(etfs: list[dict[str, Any]]) -> dict[str, Any]:
        current_weights = [finite_number(item["current_weight_pct"]) for item in etfs]
        complete = bool(etfs) and all(weight is not None for weight in current_weights)
        total = sum(weight or 0.0 for weight in current_weights)
        return {
            "status": "available" if complete and total > 0 else "data-limited",
            "input_weight_total_pct": rounded(total) if complete else None,
            "weights_sum_to_100_pct": rounded(total) == 100 if complete else None,
            "note": (
                "입력 비중을 그대로 표시합니다. 입력 비중이 없거나 합계가 0이면 "
                "현재 비중 비교와 비중 변화 계산은 data-limited입니다."
            ),
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
                coverage_available = bool(left_weights) and bool(right_weights)
                overlap = (
                    rounded(
                        sum(min(left_weights[ticker], right_weights[ticker]) for ticker in common)
                    )
                    if coverage_available
                    else None
                )
                rows.append(
                    {
                        "left_ticker": left["ticker"],
                        "right_ticker": right["ticker"],
                        "common_top10_holdings": common if coverage_available else None,
                        "minimum_confirmed_top10_overlap_pct": overlap,
                        "left_top10_coverage_pct": (
                            rounded(sum(left_weights.values())) if coverage_available else None
                        ),
                        "right_top10_coverage_pct": (
                            rounded(sum(right_weights.values())) if coverage_available else None
                        ),
                        "status": "available" if coverage_available else "data-limited",
                    }
                )
        return rows

    def _fund_metadata(self, ticker: str) -> tuple[Any | None, str]:
        try:
            return self.yf_module.Ticker(ticker), "available"
        except Exception:
            return None, "unavailable"

    @staticmethod
    def _funds_data(fund: Any | None) -> Any | None:
        if fund is None:
            return None
        try:
            return fund.funds_data
        except Exception:
            return None

    @staticmethod
    def _adjusted_close(fund: Any | None) -> pd.Series:
        if fund is None:
            return pd.Series(dtype=float)
        try:
            history = fund.history(period="5y", auto_adjust=True)
        except Exception:
            return pd.Series(dtype=float)
        return close_series(history)

    @staticmethod
    def _trailing_yield(
        distributions: Any,
        close: Any,
        current_price: float | None,
    ) -> float | None:
        price = current_price or (finite_number(close.iloc[-1]) if not close.empty else None)
        if price is None or price <= 0 or distributions.empty:
            return None
        latest = distributions.index.max()
        trailing = distributions[distributions.index > latest - pd.DateOffset(days=365)]
        return float(trailing.sum() / price * 100) if not trailing.empty else None

    @staticmethod
    def _sensitivity(ticker: str) -> dict[str, str]:
        if ticker in RATE_SENSITIVE_TICKERS:
            rate = "high"
        elif ticker in RECESSION_RESILIENT_TICKERS:
            rate = "low"
        else:
            rate = "medium"
        recession = "lower" if ticker in RECESSION_RESILIENT_TICKERS else "higher"
        return {
            "interest_rate_sensitivity": rate,
            "recession_sensitivity": recession,
            "rule_basis": "ticker exposure category; not a forecast",
        }

    def _scenarios(
        self,
        etfs: list[dict[str, Any]],
        current_weight_metadata: dict[str, Any],
    ) -> list[dict[str, Any]]:
        usable = [item for item in etfs if item["data_quality"] != "data-limited"]
        definitions = [
            (
                "aggressive",
                "최근 1년 수익률 비중이 큰 가정형 시나리오",
                "return_1y_only",
                "상대적으로 높은 방향이지만 불확실성이 큼",
                "모멘텀 반전과 성장 자산 집중",
                "큰 가격 변동을 감수하고 장기 회복을 기다릴 수 있는 투자자",
            ),
            (
                "balanced",
                "수익률·변동성·분배수익률을 함께 반영한 가정형 시나리오",
                "mixed_score",
                "중간 수준의 방향성",
                "위기 국면에서 자산 간 상관관계 상승",
                "성장과 변동성 완화를 함께 원하는 투자자",
            ),
            (
                "conservative",
                "낮은 과거 변동성과 경기방어 분류를 우선한 가정형 시나리오",
                "stability_first",
                "상대적으로 낮지만 안정 지향의 방향성",
                "금리 상승과 인플레이션 재가속",
                "자본 변동을 줄이고 방어적 노출을 선호하는 투자자",
            ),
        ]
        scenarios = []
        for (
            name,
            rationale,
            allocation_basis,
            expected_return_direction,
            primary_risk,
            suitable_investor,
        ) in definitions:
            raw = [(item["ticker"], self._scenario_score(item, name)) for item in usable]
            scored = [(ticker, score) for ticker, score in raw if score is not None and score > 0]
            targets = target_weights(scored) if scored else []
            scenarios.append(
                {
                    "name": name,
                    "rationale": rationale,
                    "expected_return_direction": expected_return_direction,
                    "primary_risk": primary_risk,
                    "suitable_investor": suitable_investor,
                    "scenario_metadata": {
                        "allocation_basis": allocation_basis,
                        "eligible_data": (
                            "fresh market data with observable 1-year return and volatility"
                        ),
                        "current_weight_comparison_status": current_weight_metadata["status"],
                        "is_forecast": False,
                    },
                    "target_weights": targets,
                    "weight_changes_vs_current_pct": self._weight_changes(
                        etfs,
                        targets,
                        current_weight_metadata["status"] == "available",
                    ),
                    "unallocated_weight_pct": rounded(
                        100 - sum(row["target_weight_pct"] for row in targets)
                    ),
                    "excluded_tickers": [item["ticker"] for item in etfs if item not in usable],
                    "review_only": True,
                }
            )
        return scenarios

    @staticmethod
    def _weight_changes(
        etfs: list[dict[str, Any]],
        targets: list[dict[str, Any]],
        current_weights_available: bool,
    ) -> list[dict[str, Any]] | None:
        if not current_weights_available:
            return None
        target_by_ticker = {item["ticker"]: item["target_weight_pct"] for item in targets}
        return [
            {
                "ticker": item["ticker"],
                "current_weight_pct": item["current_weight_pct"],
                "target_weight_pct": target_by_ticker.get(item["ticker"], 0.0),
                "change_pct_points": rounded(
                    target_by_ticker.get(item["ticker"], 0.0) - item["current_weight_pct"]
                ),
            }
            for item in etfs
        ]

    @staticmethod
    def _scenario_score(item: dict[str, Any], scenario: str) -> float | None:
        metrics = item["metrics"]
        return_1y = finite_number(metrics["return_1y_pct"])
        volatility = finite_number(metrics["annualized_volatility_pct"])
        yield_pct = finite_number(metrics["trailing_distribution_yield_pct"])
        recession = item["sensitivity"]["recession_sensitivity"]
        if return_1y is None or volatility is None:
            return None
        momentum = max(0.0, 100 + return_1y)
        stability = 100 / max(volatility, 1.0)
        income = max(yield_pct or 0.0, 0.0)
        if scenario == "aggressive":
            return momentum
        if scenario == "balanced":
            return momentum * 0.6 + stability * 0.3 + income * 0.1
        return stability * 0.7 + income * 0.2 + (20.0 if recession == "lower" else 0.0)
