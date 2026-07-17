"""Deterministic high-dividend ETF durability comparison."""

from __future__ import annotations

from typing import Any, Sequence

import pandas as pd

from app.services.advisory.features import (
    close_series,
    dividends_from_ticker,
    finite_number,
    quality_summary,
    rounded,
    sector_weights_from_funds_data,
    top_holdings_from_funds_data,
)
from app.services.market_data_service import MarketDataService

DEFAULT_HIGH_DIVIDEND_ETFS = (
    "JEPI",
    "JEPQ",
    "SCHD",
    "VYM",
    "DGRO",
    "HDV",
    "SPYD",
    "DIVO",
    "SDY",
    "NOBL",
)
RATE_SENSITIVE = {"JEPI", "JEPQ", "SPYD"}
RECESSION_RESILIENT = {"SCHD", "VYM", "DGRO", "HDV", "SDY", "NOBL"}


class HighDividendEtfService:
    """Compare income ETFs without estimating unavailable distributions or returns."""

    def __init__(self, market_data_service: MarketDataService, yf_module: Any) -> None:
        self.market_data_service = market_data_service
        self.yf_module = yf_module

    def analyze(
        self,
        tickers: Sequence[str] = DEFAULT_HIGH_DIVIDEND_ETFS,
        stale_data_business_days: int = 2,
        min_distribution_yield_percent: float | None = None,
    ) -> dict[str, Any]:
        etfs = [self._analyze_etf(ticker, stale_data_business_days) for ticker in tickers]
        rankable = [
            item
            for item in etfs
            if item["stability_score"] is not None
            and (
                min_distribution_yield_percent is None
                or (
                    item["distribution"]["trailing_12m_distribution_yield_pct"] is not None
                    and item["distribution"]["trailing_12m_distribution_yield_pct"]
                    >= min_distribution_yield_percent
                )
            )
        ]
        rankable.sort(key=lambda item: (item["stability_score"], item["ticker"]))
        five = min(5, len(rankable) // 2) if len(rankable) < 10 else 5
        caution = rankable[:five]
        stable = list(reversed(rankable[-five:])) if five else []
        evidence = [item["evidence"] for item in etfs]
        return {
            "analysis_type": "high_dividend_etfs",
            "etfs": etfs,
            "caution_etfs": caution,
            "relatively_stable_etfs": stable,
            "classification_note": (
                "과거 분배금과 보유종목 지표는 미래 분배금 또는 수익을 보장하지 않습니다. "
                "분배금 감소 위험은 과거 12개월 분배금 비교에 한정된 관찰값입니다."
            ),
            "beginner_explanation": (
                "분배금 수익률은 현재 가격 대비 지급액만 보여줍니다. ETF 가격이 크게 떨어졌거나 "
                "일시적인 특별분배가 있었어도 수익률은 높아 보일 수 있습니다. 따라서 분배금을 "
                "포함한 장기 총수익률, 분배금의 지속성, 보유종목의 질과 섹터 쏠림을 "
                "함께 확인해야 합니다."
            ),
            "data_quality": quality_summary(evidence),
            "evidence": evidence,
        }

    def _analyze_etf(self, ticker: str, stale_data_business_days: int) -> dict[str, Any]:
        symbol = str(ticker).strip().upper()
        market_data = self.market_data_service.fetch_price_history(
            "ETF", symbol, lookback_days=2_600, stale_data_business_days=stale_data_business_days
        )
        close = close_series(market_data.dataframe)
        fund, ticker_status = self._ticker(symbol)
        funds_data = self._funds_data(fund)
        adjusted_close = self._adjusted_close(fund)
        distributions = dividends_from_ticker(fund) if fund is not None else pd.Series(dtype=float)
        sectors, sector_status = sector_weights_from_funds_data(funds_data)
        holdings, holdings_status = top_holdings_from_funds_data(funds_data)
        holdings_quality = self._holdings_quality(holdings)
        total_return_5y = self._total_return(adjusted_close, 5)
        total_return_10y = self._total_return(adjusted_close, 10)
        current_price = finite_number(market_data.current_price)
        distribution = self._distribution_metrics(
            distributions,
            current_price if not market_data.is_stale else None,
        )
        sector = sectors[0] if sectors else None
        score = self._stability_score(distribution, sector)
        evidence = {
            "ticker": symbol,
            "provider": market_data.provider,
            "last_trading_date": (
                market_data.last_trading_date.isoformat() if market_data.last_trading_date else None
            ),
            "market_data_note": market_data.data_quality_note,
            "ticker_status": ticker_status,
            "adjusted_history_status": "available" if not adjusted_close.empty else "unavailable",
            "distribution_history_status": (
                "available" if not distributions.empty else "unavailable"
            ),
            "sector_status": sector_status,
            "holdings_status": holdings_status,
            "holdings_quality_status": holdings_quality["status"],
            "status": "available" if not market_data.is_stale and not close.empty else "limited",
        }
        return {
            "ticker": symbol,
            "total_return_5y_pct": rounded(total_return_5y),
            "total_return_10y_pct": rounded(total_return_10y),
            "distribution": distribution,
            "top_holdings": holdings,
            "holdings_quality": holdings_quality,
            "sector_concentration": {
                "dominant_sector": sector["sector"] if sector else None,
                "dominant_sector_weight_pct": sector["weight_pct"] if sector else None,
                "sector_weights": sectors,
            },
            "suitability": self._suitability(symbol, distribution, sector),
            "stability_score": rounded(score),
            "data_quality": "fresh" if evidence["status"] == "available" else "data-limited",
            "evidence": evidence,
        }

    def _ticker(self, ticker: str) -> tuple[Any | None, str]:
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
            history = fund.history(period="10y", auto_adjust=True)
        except Exception:
            return pd.Series(dtype=float)
        return close_series(history)

    @staticmethod
    def _total_return(close: pd.Series, years: int) -> float | None:
        sessions = years * 252
        if len(close) <= sessions:
            return None
        start = finite_number(close.iloc[-sessions - 1])
        end = finite_number(close.iloc[-1])
        if start is None or end is None or start <= 0:
            return None
        return (end / start - 1) * 100

    @staticmethod
    def _distribution_metrics(
        distributions: pd.Series,
        current_price: float | None,
    ) -> dict[str, Any]:
        if distributions.empty:
            return {
                "trailing_12m_distribution_amount": None,
                "trailing_12m_distribution_yield_pct": None,
                "as_of_distribution_date": None,
                "growth_3y_pct": None,
                "stability": "data-limited",
                "paid_years": 0,
                "distribution_cut_risk": {
                    "status": "data-limited",
                    "latest_vs_prior_12m_change_pct": None,
                    "risk_level": "data-limited",
                    "basis": "distribution history unavailable",
                },
            }
        latest = distributions.index.max()
        trailing = distributions[distributions.index > latest - pd.DateOffset(days=365)]
        previous = distributions[
            (distributions.index > latest - pd.DateOffset(days=730))
            & (distributions.index <= latest - pd.DateOffset(days=365))
        ]
        trailing_amount = finite_number(trailing.sum()) if not trailing.empty else None
        previous_amount = finite_number(previous.sum()) if not previous.empty else None
        change = None
        if trailing_amount is not None and previous_amount is not None and previous_amount > 0:
            change = (trailing_amount / previous_amount - 1) * 100
        if change is None:
            risk_level = "data-limited"
        elif change <= -10:
            risk_level = "elevated_observed_cut"
        else:
            risk_level = "no_material_observed_cut"
        annual = distributions.groupby(distributions.index.year).sum()
        paid = annual[annual > 0]
        growth = None
        if len(paid) >= 4:
            first = finite_number(paid.iloc[-4])
            last = finite_number(paid.iloc[-1])
            if first is not None and last is not None and first > 0:
                growth = ((last / first) ** (1 / 3) - 1) * 100
        stable_history = len(paid) >= 4 and (paid.pct_change().dropna() >= -0.1).all()
        stability = "stable" if stable_history else "variable"
        return {
            "trailing_12m_distribution_amount": rounded(trailing_amount),
            "trailing_12m_distribution_yield_pct": rounded(
                trailing_amount / current_price * 100
                if trailing_amount is not None and current_price is not None and current_price > 0
                else None
            ),
            "as_of_distribution_date": latest.date().isoformat(),
            "growth_3y_pct": rounded(growth),
            "stability": stability,
            "paid_years": int(len(paid)),
            "distribution_cut_risk": {
                "status": "available" if change is not None else "data-limited",
                "latest_vs_prior_12m_change_pct": rounded(change),
                "risk_level": risk_level,
                "basis": "latest available 12 months versus prior 12 months; not a forecast",
            },
        }

    def _holdings_quality(self, holdings: list[dict[str, Any]]) -> dict[str, Any]:
        observations = [self._holding_quality(holding) for holding in holdings]
        observed_weight = sum(
            observation["weight_pct"]
            for observation in observations
            if observation["quality_metrics_status"] == "available"
        )
        total_weight = sum(holding["weight_pct"] for holding in holdings)
        return {
            "status": "available" if observations and observed_weight > 0 else "data-limited",
            "top10_coverage_pct": rounded(total_weight) if holdings else None,
            "quality_metrics_coverage_pct": rounded(observed_weight) if holdings else None,
            "holdings": observations,
            "note": (
                "보유종목 품질은 yfinance가 제공한 수익성·자본수익률·부채 지표만 표시하며, "
                "누락 지표는 평가하거나 추정하지 않습니다."
            ),
        }

    def _holding_quality(self, holding: dict[str, Any]) -> dict[str, Any]:
        info: dict[str, Any] = {}
        try:
            raw_info = getattr(self.yf_module.Ticker(holding["ticker"]), "info", {}) or {}
            info = raw_info if isinstance(raw_info, dict) else {}
        except Exception:
            pass
        profit_margin = self._percent_metric(info.get("profitMargins"))
        return_on_equity = self._percent_metric(info.get("returnOnEquity"))
        debt_to_equity = finite_number(info.get("debtToEquity"))
        available = any(
            value is not None for value in (profit_margin, return_on_equity, debt_to_equity)
        )
        return {
            "ticker": holding["ticker"],
            "weight_pct": holding["weight_pct"],
            "profit_margin_pct": rounded(profit_margin),
            "return_on_equity_pct": rounded(return_on_equity),
            "debt_to_equity": rounded(debt_to_equity),
            "quality_metrics_status": "available" if available else "data-limited",
        }

    @staticmethod
    def _percent_metric(value: Any) -> float | None:
        number = finite_number(value)
        if number is None:
            return None
        return number * 100 if -1 <= number <= 1 else number

    @staticmethod
    def _suitability(
        ticker: str,
        distribution: dict[str, Any],
        sector: dict[str, Any] | None,
    ) -> dict[str, str]:
        rate = "high" if ticker in RATE_SENSITIVE else "medium"
        recession = "relatively_resilient" if ticker in RECESSION_RESILIENT else "needs_review"
        concentration = finite_number(sector["weight_pct"]) if sector else None
        long_term = "needs_review"
        if distribution["stability"] == "stable" and (concentration is None or concentration < 40):
            long_term = "relatively_suitable"
        return {
            "interest_rate_sensitivity": rate,
            "recession_suitability": recession,
            "long_term_suitability": long_term,
            "rule_basis": (
                "distribution history, sector concentration, and ticker exposure category"
            ),
        }

    @staticmethod
    def _stability_score(
        distribution: dict[str, Any], sector: dict[str, Any] | None
    ) -> float | None:
        if distribution["stability"] == "data-limited":
            return None
        score = 60.0 if distribution["stability"] == "stable" else 35.0
        growth = finite_number(distribution["growth_3y_pct"])
        if growth is not None:
            score += min(max(growth, -20.0), 20.0)
        concentration = finite_number(sector["weight_pct"]) if sector else None
        if concentration is not None and concentration >= 40:
            score -= 15.0
        return min(max(score, 0.0), 100.0)
