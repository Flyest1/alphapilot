"""Six-month, data-derived sector proxy outlook with investor scenarios."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from app.services.advisory.features import (
    annualized_volatility,
    close_series,
    finite_number,
    period_return,
    quality_summary,
    rounded,
    target_weights,
    top_holdings_from_funds_data,
)
from app.services.market_data_service import MarketDataService

SECTOR_BOND_PROXIES = {
    "technology": "XLK",
    "semiconductors": "SMH",
    "healthcare": "XLV",
    "financials": "XLF",
    "energy": "XLE",
    "consumer_discretionary": "XLY",
    "industrials": "XLI",
    "utilities": "XLU",
    "real_estate": "XLRE",
    "long_treasury_bonds": "TLT",
}
DEFENSIVE_PROXIES = {"XLV", "XLU", "TLT"}
FRED_NOTICE = (
    "This product uses the FRED® API but is not endorsed or certified by the "
    "Federal Reserve Bank of St. Louis."
)
MACRO_SERIES = ("FEDFUNDS", "DGS2", "DGS10", "T10Y2Y", "CPIAUCSL", "CPILFESL")


class SectorOutlookService:
    """Calculate an observable six-month attractiveness score; it is not a forecast."""

    def __init__(
        self,
        market_data_service: MarketDataService,
        yf_module: Any | None = None,
        macro_provider: Any | None = None,
        fund_flow_provider: Any | None = None,
    ) -> None:
        self.market_data_service = market_data_service
        self.yf_module = yf_module
        self.macro_provider = macro_provider
        self.fund_flow_provider = fund_flow_provider

    def analyze(
        self,
        proxies: Mapping[str, str] = SECTOR_BOND_PROXIES,
        stale_data_business_days: int = 2,
    ) -> dict[str, Any]:
        macro_context = self._macro_context()
        sectors = [
            self._analyze_proxy(name, ticker, stale_data_business_days)
            for name, ticker in proxies.items()
        ]
        evidence = [item["evidence"] for item in sectors]
        macro_evidence = macro_context.get("evidence", [])
        evidence.extend(
            macro_evidence
            or [
                {
                    "evidence_id": "fred:unavailable",
                    "provider": "fred",
                    "status": "limited",
                    "limitations": macro_context.get("limitations", []),
                }
            ]
        )
        return {
            "analysis_type": "sector_outlook",
            "proxy_universe": dict(proxies),
            "sectors": sectors,
            "macro_context": macro_context,
            "investor_portfolios": self._portfolios(sectors),
            "data_quality": quality_summary(evidence),
            "evidence": evidence,
            "methodology": (
                "최근 6개월 수익률, 60일 이동평균 대비 추세, 과거 변동성으로 계산한 "
                "관찰 지표이며 6개월 전망이나 수익 보장이 아닙니다."
            ),
            "safety_note": (
                "대표 종목은 yfinance의 ETF 상위 10개 보유종목이 제공될 때만 표시합니다. "
                "가격 기반 지표는 금리·인플레이션·실적·밸류에이션의 미래 변화를 예측하지 않습니다."
            ),
            "fred_notice": FRED_NOTICE if macro_context.get("provider") == "fred" else None,
        }

    def _analyze_proxy(
        self,
        name: str,
        ticker: str,
        stale_data_business_days: int,
    ) -> dict[str, Any]:
        market_data = self.market_data_service.fetch_price_history(
            "ETF", ticker, lookback_days=200, stale_data_business_days=stale_data_business_days
        )
        close = close_series(market_data.dataframe)
        return_6m = period_return(close, 126)
        trend = self._trend(close)
        volatility = annualized_volatility(close, 126)
        score = self._attractiveness(return_6m, trend, volatility, market_data.is_stale)
        fund = self._ticker(ticker)
        holdings, holdings_status = self._representative_holdings(fund)
        fundamentals, fundamentals_status = self._fundamentals(fund)
        flow_context = self._flow_context(ticker, market_data)
        status = (
            "limited"
            if score is None
            else (
                "available"
                if (
                    holdings_status == "available"
                    and fundamentals_status == "available"
                    and flow_context["status"] == "available"
                )
                else "partial"
            )
        )
        evidence = {
            "sector": name,
            "ticker": ticker,
            "provider": market_data.provider,
            "last_trading_date": (
                market_data.last_trading_date.isoformat() if market_data.last_trading_date else None
            ),
            "market_data_note": market_data.data_quality_note,
            "representative_holdings_status": holdings_status,
            "fundamentals_status": fundamentals_status,
            "etf_flow_status": flow_context["status"],
            "etf_flow_provider": flow_context["provider"],
            "status": status,
        }
        return {
            "sector": name,
            "ticker": ticker,
            "return_6m_pct": rounded(return_6m),
            "trend_vs_60d_ma_pct": rounded(trend),
            "annualized_volatility_pct": rounded(volatility),
            "attractiveness_score": rounded(score),
            "attractiveness_label": self._label(score),
            "favorable_factors": self._favorable_factors(return_6m, trend, score),
            "unfavorable_factors": self._unfavorable_factors(
                return_6m,
                trend,
                volatility,
                score,
            ),
            "representative_holdings": holdings,
            "fundamentals": fundamentals,
            "etf_flow_context": flow_context,
            "risk": self._risk(volatility, market_data.is_stale),
            "safety_note": "관찰 지표이며 투자 권유 또는 미래 수익 예측이 아닙니다.",
            "data_quality": (
                "fresh"
                if status == "available"
                else "partial" if status == "partial" else "data-limited"
            ),
            "evidence": evidence,
        }

    def _macro_context(self) -> dict[str, Any]:
        if self.macro_provider is None:
            return {
                "provider": "fred",
                "status": "unavailable",
                "series": [],
                "evidence": [],
                "limitations": ["FRED provider is not configured."],
            }
        end = datetime.now(timezone.utc).date()
        try:
            context = self.macro_provider.fetch_context(
                MACRO_SERIES,
                observation_start=end - timedelta(days=400),
                observation_end=end,
            )
        except Exception:
            return {
                "provider": "fred",
                "status": "unavailable",
                "series": [],
                "evidence": [],
                "limitations": ["FRED macro data could not be retrieved."],
            }
        series_rows = []
        evidence = []
        for series in context.get("series", []):
            observations = series.get("observations") or []
            if not observations:
                continue
            latest = observations[-1]
            previous = observations[-2] if len(observations) > 1 else None
            year_ago = observations[-13] if len(observations) >= 13 else None
            row = {
                "series_id": series.get("series_id"),
                "label": series.get("label"),
                "category": series.get("category"),
                "units": series.get("units"),
                "frequency": series.get("frequency"),
                "latest": latest,
                "previous_value": previous.get("value") if previous else None,
                "year_ago_value": year_ago.get("value") if year_ago else None,
                "realtime_vintage": series.get("realtime_vintage"),
            }
            series_rows.append(row)
            evidence.append(
                {
                    "evidence_id": (
                        f"fred:{series.get('series_id')}:{latest.get('observation_date')}:"
                        f"{context.get('retrieved_at')}"
                    ),
                    "provider": "fred",
                    "title": series.get("label"),
                    "as_of": latest.get("observation_date"),
                    "retrieved_at": context.get("retrieved_at"),
                    "value": latest.get("value"),
                    "units": series.get("units"),
                    "series_id": series.get("series_id"),
                    "realtime_vintage": series.get("realtime_vintage"),
                    "status": "available",
                }
            )
        return {
            "provider": "fred",
            "status": context.get("status"),
            "retrieved_at": context.get("retrieved_at"),
            "series": series_rows,
            "evidence": evidence,
            "limitations": context.get("limitations") or [],
        }

    def _flow_context(self, ticker: str, market_data: Any) -> dict[str, Any]:
        if self.fund_flow_provider is not None:
            try:
                nport = self.fund_flow_provider.get_nport_delayed_data(ticker)
            except Exception:
                nport = {}
            if nport.get("status") in {"available", "data_limited"}:
                return {
                    "provider": "sec_edgar_nport",
                    "status": nport.get("status"),
                    "series_id": nport.get("series_id"),
                    "public_data_delay_days": nport.get("public_data_delay_days"),
                    "flow_fields": nport.get("flow_fields") or {},
                    "filings": nport.get("filings") or [],
                    "limitations": [
                        "SEC N-PORT public data is delayed and is not current daily ETF flow data."
                    ],
                }
        frame = getattr(market_data, "dataframe", None)
        volume_change = None
        volume_column = next(
            (column for column in ("Volume", "volume") if frame is not None and column in frame),
            None,
        )
        if volume_column is not None and len(frame[volume_column].dropna()) >= 40:
            volume = frame[volume_column].dropna()
            prior = finite_number(volume.iloc[-40:-20].mean())
            recent = finite_number(volume.iloc[-20:].mean())
            if prior not in (None, 0) and recent is not None:
                volume_change = (recent / prior - 1) * 100
        return {
            "provider": "yfinance_price_volume_proxy",
            "status": "proxy" if volume_change is not None else "data-limited",
            "volume_20d_vs_prior_20d_pct": rounded(volume_change),
            "limitations": [
                "This is a price/volume activity proxy, not actual ETF subscriptions "
                "or redemptions."
            ],
        }

    def _ticker(self, ticker: str) -> Any | None:
        try:
            yf_module = self.yf_module or self.market_data_service._yf_module()
            return yf_module.Ticker(ticker)
        except Exception:
            return None

    @staticmethod
    def _representative_holdings(fund: Any | None) -> tuple[list[dict[str, Any]], str]:
        if fund is None:
            return [], "data-limited"
        try:
            return top_holdings_from_funds_data(getattr(fund, "funds_data", None), limit=10)
        except Exception:
            return [], "data-limited"

    @staticmethod
    def _fundamentals(fund: Any | None) -> tuple[dict[str, Any], str]:
        if fund is None:
            return {}, "data-limited"
        try:
            info = fund.info or {}
        except Exception:
            return {}, "data-limited"
        fundamentals = {
            "earnings_growth_pct": rounded(
                finite_number(info.get("earningsGrowth")) * 100
                if finite_number(info.get("earningsGrowth")) is not None
                else None
            ),
            "revenue_growth_pct": rounded(
                finite_number(info.get("revenueGrowth")) * 100
                if finite_number(info.get("revenueGrowth")) is not None
                else None
            ),
            "trailing_pe": rounded(finite_number(info.get("trailingPE"))),
            "forward_pe": rounded(finite_number(info.get("forwardPE"))),
            "price_to_book": rounded(finite_number(info.get("priceToBook"))),
            "basis": "yfinance ETF quote metadata; availability and definition vary by fund",
        }
        available = any(value is not None for key, value in fundamentals.items() if key != "basis")
        return fundamentals, "available" if available else "data-limited"

    @staticmethod
    def _favorable_factors(
        return_6m: float | None,
        trend: float | None,
        score: float | None,
    ) -> list[dict[str, Any]] | None:
        if score is None:
            return None
        factors = []
        if return_6m is not None and return_6m > 0:
            factors.append(
                {
                    "metric": "return_6m_pct",
                    "value": rounded(return_6m),
                    "observation": "positive",
                }
            )
        if trend is not None and trend > 0:
            factors.append(
                {
                    "metric": "trend_vs_60d_ma_pct",
                    "value": rounded(trend),
                    "observation": "above_60d_average",
                }
            )
        return factors

    @staticmethod
    def _unfavorable_factors(
        return_6m: float | None,
        trend: float | None,
        volatility: float | None,
        score: float | None,
    ) -> list[dict[str, Any]] | None:
        if score is None:
            return None
        factors = []
        if return_6m is not None and return_6m <= 0:
            factors.append(
                {
                    "metric": "return_6m_pct",
                    "value": rounded(return_6m),
                    "observation": "non_positive",
                }
            )
        if trend is not None and trend <= 0:
            factors.append(
                {
                    "metric": "trend_vs_60d_ma_pct",
                    "value": rounded(trend),
                    "observation": "at_or_below_60d_average",
                }
            )
        if volatility is not None:
            factors.append(
                {
                    "metric": "annualized_volatility_pct",
                    "value": rounded(volatility),
                    "observation": "historical_price_variability",
                }
            )
        return factors

    @staticmethod
    def _risk(volatility: float | None, is_stale: bool) -> dict[str, Any]:
        if is_stale or volatility is None:
            return {"status": "data-limited", "annualized_volatility_pct": None}
        return {
            "status": "available",
            "annualized_volatility_pct": rounded(volatility),
            "basis": (
                "historical volatility only; it does not measure all sector, duration, "
                "or macro risks"
            ),
        }

    @staticmethod
    def _trend(close: Any) -> float | None:
        if len(close) < 60:
            return None
        average = finite_number(close.tail(60).mean())
        latest = finite_number(close.iloc[-1])
        if average is None or latest is None or average <= 0:
            return None
        return (latest / average - 1) * 100

    @staticmethod
    def _attractiveness(
        return_6m: float | None,
        trend: float | None,
        volatility: float | None,
        is_stale: bool,
    ) -> float | None:
        if is_stale or return_6m is None or trend is None or volatility is None:
            return None
        return min(max(50 + return_6m * 0.8 + trend * 0.2 - volatility * 0.5, 0), 100)

    @staticmethod
    def _label(score: float | None) -> str:
        if score is None:
            return "data-limited"
        if score >= 65:
            return "relatively_attractive"
        if score >= 45:
            return "neutral"
        return "less_attractive"

    def _portfolios(self, sectors: list[dict[str, Any]]) -> list[dict[str, Any]]:
        definitions = [
            ("aggressive", "점수 중심, 변동성 허용", 0.0, False),
            ("balanced", "점수와 변동성을 함께 반영", 0.5, False),
            ("conservative", "방어 분류와 과거 변동성 완화 우선", 1.0, True),
        ]
        portfolios = []
        for name, rationale, volatility_weight, defensive in definitions:
            scored = []
            for item in sectors:
                score = finite_number(item["attractiveness_score"])
                volatility = finite_number(item["annualized_volatility_pct"])
                if score is None or volatility is None:
                    continue
                raw = score / max(volatility * volatility_weight, 1.0)
                if defensive and item["ticker"] in DEFENSIVE_PROXIES:
                    raw *= 1.5
                scored.append((item["ticker"], raw))
            allocations = target_weights(scored) if scored else []
            allocated_tickers = {row["ticker"] for row in allocations}
            portfolios.append(
                {
                    "investor_profile": name,
                    "rationale": rationale,
                    "target_weights": allocations,
                    "excluded_tickers": [
                        item["ticker"]
                        for item in sectors
                        if item["ticker"] not in allocated_tickers
                    ],
                    "review_only": True,
                }
            )
        return portfolios
