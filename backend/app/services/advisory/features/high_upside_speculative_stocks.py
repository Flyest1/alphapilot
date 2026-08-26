from __future__ import annotations

from math import sqrt
from typing import Any, Mapping

import pandas as pd

from app.services.advisory.features.common import (
    data_quality,
    evidence_item,
    finite_float,
    now_iso,
    percent_change,
    period_return,
    rounded,
    statement_values,
    ticker_snapshot,
)

MIN_MARKET_CAP_USD = 50_000_000
MAX_MARKET_CAP_USD = 10_000_000_000
MIN_MEDIAN_DOLLAR_VOLUME_USD = 1_000_000
MIN_CASH_RUNWAY_QUARTERS = 4.0

_CATALYST_TERMS = {
    "clinical_milestone": ("clinical trial", "phase 1", "phase 2", "phase 3", "pivotal trial"),
    "regulatory_milestone": ("food and drug administration", " fda ", "regulatory approval"),
    "commercial_milestone": ("commercial launch", "strategic partnership", "material contract"),
}
_DILUTION_TERMS = (
    "at-the-market offering",
    "at the market offering",
    "common stock offering",
    "convertible notes",
    "convertible debt",
    "dilution",
)
_GOING_CONCERN_TERMS = ("going concern", "substantial doubt")
_BIOTECH_TERMS = ("biotechnology", "biotech", "pharmaceutical", "life science", "therapeutics")


class HighUpsideSpeculativeStocksAnalyzer:
    """Rank evidence-backed US speculative equities without estimating jackpot probability."""

    def __init__(
        self,
        market_data_service: Any,
        yf_module: Any,
        filing_provider: Any | None = None,
        now_provider: Any | None = None,
    ) -> None:
        self.market_data_service = market_data_service
        self.yf_module = yf_module
        self.filing_provider = filing_provider
        self.now_provider = now_provider

    def analyze(self, tickers: list[str], limit: int = 5) -> dict[str, Any]:
        generated_at = now_iso(self.now_provider)
        rows = [
            self._analyze_ticker(ticker.upper(), generated_at)
            for ticker in dict.fromkeys(tickers)
            if str(ticker).strip()
        ]
        eligible = [row for row in rows if row["candidate_eligible"]]
        eligible.sort(key=lambda row: (-row["asymmetric_opportunity_score"], row["ticker"]))
        top_count = max(1, min(limit, 20))
        top_candidates = [
            row for row in eligible if row["classification"] == "deeper_research_candidate"
        ]
        watch = [row for row in eligible if row["classification"] == "speculative_watch"]
        rejected = [row for row in rows if not row["candidate_eligible"]]
        return {
            "analysis_type": "high_upside_speculative_stocks",
            "generated_at": generated_at,
            "rows": rows,
            "top_candidates": top_candidates[:top_count],
            "speculative_watch": watch[:top_count],
            "rejected_or_data_limited": rejected,
            "screening_scope": {
                "listing_scope": "US-listed public equities only",
                "private_startups_excluded": True,
                "market_cap_range_usd": {
                    "minimum": MIN_MARKET_CAP_USD,
                    "maximum": MAX_MARKET_CAP_USD,
                },
                "minimum_median_dollar_volume_usd": MIN_MEDIAN_DOLLAR_VOLUME_USD,
            },
            "scoring_methodology": {
                "asymmetric_opportunity_score": (
                    "Relative ranking score: 70% upside evidence and 30% inverse downside risk. "
                    "It is not a success probability or expected return."
                ),
                "action_policy": "All rows remain WATCH until separate due diligence.",
            },
            "evidence": self._evidence(rows),
            "data_quality": data_quality(
                rows,
                [
                    "yfinance의 공격형 소형주 스크리너는 후보 발견용이며 "
                    "전체 시장을 대표하지 않습니다.",
                    "SEC 공시 문구는 촉매·희석·계속기업 위험의 존재만 분류하며 "
                    "임상 성공을 예측하지 않습니다.",
                    "점수는 상대 비교 지표이며 대박 확률·목표수익률이 아닙니다.",
                ],
            ),
            "disclaimer": (
                "전액 손실, 희석, 유동성 및 바이오 임상·규제 실패 위험이 큰 관찰 후보입니다. "
                "투자 의사결정 지원 정보이며 수익을 보장하지 않습니다."
            ),
        }

    def _analyze_ticker(self, ticker: str, retrieved_at: str) -> dict[str, Any]:
        market_data = self.market_data_service.fetch_price_history("US", ticker, 260)
        snapshot = ticker_snapshot(self.yf_module, ticker)
        info = snapshot["info"]
        financials = snapshot["quarterly_financials"]
        cashflow = snapshot["quarterly_cashflow"]
        balance_sheet = snapshot["quarterly_balance_sheet"]
        revenue, previous_revenue = statement_values(
            financials, ("Total Revenue", "Operating Revenue")
        )
        free_cash_flow, _ = statement_values(cashflow, ("Free Cash Flow",))
        cash, _ = statement_values(
            balance_sheet,
            ("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"),
        )
        debt, _ = statement_values(balance_sheet, ("Total Debt",))
        filings = self._filings(ticker)
        filing_text = " ".join(str(row.get("text") or "") for row in filings).casefold()
        catalysts = [
            category
            for category, terms in _CATALYST_TERMS.items()
            if any(term in filing_text for term in terms)
        ]
        dilution_signal = any(term in filing_text for term in _DILUTION_TERMS)
        going_concern_signal = any(term in filing_text for term in _GOING_CONCERN_TERMS)
        market_cap = finite_float(info.get("marketCap"))
        median_dollar_volume = self._median_dollar_volume(market_data)
        volatility = self._annualized_volatility(market_data)
        max_drawdown = self._max_drawdown(market_data)
        six_month_return = period_return(market_data, 126)
        revenue_growth = percent_change(revenue, previous_revenue)
        cash_runway = self._cash_runway(cash, free_cash_flow)
        fresh_market = (
            not bool(getattr(market_data, "is_stale", True))
            and getattr(market_data, "last_trading_date", None) is not None
        )
        rejection_reasons = self._rejection_reasons(
            fresh_market=fresh_market,
            market_cap=market_cap,
            median_dollar_volume=median_dollar_volume,
            cash=cash,
            free_cash_flow=free_cash_flow,
            cash_runway=cash_runway,
            filings=filings,
            going_concern_signal=going_concern_signal,
        )
        eligible = not rejection_reasons
        upside_score = self._upside_score(
            market_cap, revenue_growth, six_month_return, catalysts, cash_runway, free_cash_flow
        )
        risk_score = self._risk_score(
            volatility,
            max_drawdown,
            cash,
            debt,
            cash_runway,
            free_cash_flow,
            dilution_signal,
            going_concern_signal,
        )
        asymmetric_score = round(upside_score * 0.7 + (100 - risk_score) * 0.3)
        classification = (
            "rejected_or_data_limited"
            if not eligible
            else (
                "deeper_research_candidate"
                if asymmetric_score >= 55 and catalysts
                else "speculative_watch"
            )
        )
        profile_text = " ".join(
            str(info.get(key) or "") for key in ("sector", "industry", "longBusinessSummary")
        ).casefold()
        last_trading_date = getattr(market_data, "last_trading_date", None)
        last_trading_date = last_trading_date.isoformat() if last_trading_date else None
        return {
            "ticker": ticker,
            "name": info.get("longName") or info.get("shortName") or ticker,
            "speculative_track": (
                "biotech"
                if any(term in profile_text for term in _BIOTECH_TERMS)
                else "emerging_growth"
            ),
            "market_cap_usd": rounded(market_cap, 0),
            "median_dollar_volume_usd": rounded(median_dollar_volume, 0),
            "quarterly_revenue_growth_pct": revenue_growth,
            "six_month_return_pct": six_month_return,
            "annualized_volatility_pct": volatility,
            "max_drawdown_pct": max_drawdown,
            "cash_usd": rounded(cash, 0),
            "debt_usd": rounded(debt, 0),
            "cash_runway_quarters": cash_runway,
            "official_catalyst_categories": catalysts,
            "dilution_signal": dilution_signal,
            "going_concern_signal": going_concern_signal,
            "upside_evidence_score": upside_score,
            "downside_risk_score": risk_score,
            "asymmetric_opportunity_score": asymmetric_score,
            "classification": classification,
            "action": "WATCH",
            "candidate_eligible": eligible,
            "rejection_reasons": rejection_reasons,
            "analysis_status": "available" if eligible else "data-limited",
            "provider": getattr(market_data, "provider", "yfinance"),
            "last_trading_date": last_trading_date,
            "source_as_of": last_trading_date,
            "retrieved_at": retrieved_at,
            "is_stale": not fresh_market,
            "sec_filings": [self._filing_summary(row) for row in filings],
        }

    def _filings(self, ticker: str) -> list[dict[str, Any]]:
        if self.filing_provider is None:
            return []
        try:
            try:
                rows = self.filing_provider.list_recent_filings(
                    ticker, ("10-K", "10-Q", "8-K"), limit_per_form=1, lookback_days=365
                )
            except TypeError:
                rows = self.filing_provider.list_recent_filings(ticker, ("10-K", "10-Q", "8-K"))
        except Exception:
            return []
        return [dict(row) for row in rows or [] if isinstance(row, Mapping) and row.get("text")]

    @staticmethod
    def _rejection_reasons(**values: Any) -> list[str]:
        reasons: list[str] = []
        market_cap = values["market_cap"]
        if not values["fresh_market"]:
            reasons.append("stale_or_missing_price_history")
        if market_cap is None:
            reasons.append("market_cap_unavailable")
        elif not MIN_MARKET_CAP_USD <= market_cap <= MAX_MARKET_CAP_USD:
            reasons.append("market_cap_outside_scope")
        liquidity = values["median_dollar_volume"]
        if liquidity is None or liquidity < MIN_MEDIAN_DOLLAR_VOLUME_USD:
            reasons.append("insufficient_liquidity_evidence")
        if values["cash"] is None:
            reasons.append("cash_balance_unavailable")
        if values["free_cash_flow"] is None:
            reasons.append("free_cash_flow_unavailable")
        if not values["filings"]:
            reasons.append("official_filing_evidence_unavailable")
        if values["going_concern_signal"]:
            reasons.append("going_concern_signal")
        if (
            values["free_cash_flow"] is not None
            and values["free_cash_flow"] < 0
            and (values["cash_runway"] is None or values["cash_runway"] < MIN_CASH_RUNWAY_QUARTERS)
        ):
            reasons.append("cash_runway_below_four_quarters")
        return reasons

    @staticmethod
    def _upside_score(
        market_cap: float | None,
        revenue_growth: float | None,
        momentum: float | None,
        catalysts: list[str],
        cash_runway: float | None,
        free_cash_flow: float | None,
    ) -> int:
        score = 15 + min(len(catalysts) * 12, 30)
        if revenue_growth is not None and revenue_growth > 0:
            score += min(revenue_growth / 2, 20)
        if momentum is not None and momentum > 0:
            score += min(momentum / 3, 15)
        if market_cap is not None and market_cap <= 2_000_000_000:
            score += 10
        if (free_cash_flow is not None and free_cash_flow >= 0) or (
            cash_runway is not None and cash_runway >= 8
        ):
            score += 10
        return max(0, min(round(score), 100))

    @staticmethod
    def _risk_score(
        volatility: float | None,
        max_drawdown: float | None,
        cash: float | None,
        debt: float | None,
        cash_runway: float | None,
        free_cash_flow: float | None,
        dilution_signal: bool,
        going_concern_signal: bool,
    ) -> int:
        score = 25
        if volatility is None:
            score += 20
        else:
            score += min(volatility / 4, 20)
        if max_drawdown is None:
            score += 15
        else:
            score += min(abs(max_drawdown) / 4, 20)
        if debt is not None and cash is not None and debt > cash:
            score += 10
        if free_cash_flow is not None and free_cash_flow < 0:
            score += 10 if cash_runway is None else max(0, 10 - cash_runway)
        if dilution_signal:
            score += 15
        if going_concern_signal:
            score += 30
        return max(0, min(round(score), 100))

    @staticmethod
    def _cash_runway(cash: float | None, quarterly_fcf: float | None) -> float | None:
        if cash is None or quarterly_fcf is None or quarterly_fcf >= 0:
            return None
        return rounded(cash / abs(quarterly_fcf), 1)

    @staticmethod
    def _median_dollar_volume(market_data: Any) -> float | None:
        frame = getattr(market_data, "dataframe", None)
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return None
        if "close" not in frame or "volume" not in frame:
            return None
        values = (
            (
                pd.to_numeric(frame["close"], errors="coerce")
                * pd.to_numeric(frame["volume"], errors="coerce")
            )
            .dropna()
            .tail(20)
        )
        return finite_float(values.median()) if not values.empty else None

    @staticmethod
    def _annualized_volatility(market_data: Any) -> float | None:
        frame = getattr(market_data, "dataframe", None)
        if not isinstance(frame, pd.DataFrame) or "close" not in frame:
            return None
        returns = pd.to_numeric(frame["close"], errors="coerce").pct_change().dropna().tail(252)
        return rounded(returns.std() * sqrt(252) * 100) if len(returns) >= 20 else None

    @staticmethod
    def _max_drawdown(market_data: Any) -> float | None:
        frame = getattr(market_data, "dataframe", None)
        if not isinstance(frame, pd.DataFrame) or "close" not in frame:
            return None
        closes = pd.to_numeric(frame["close"], errors="coerce").dropna().tail(252)
        if len(closes) < 2:
            return None
        return rounded(((closes / closes.cummax()) - 1).min() * 100)

    @staticmethod
    def _filing_summary(filing: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "form": filing.get("form"),
            "filed_at": filing.get("filed_at"),
            "accession_number": filing.get("accession_number"),
            "source_url": filing.get("url"),
        }

    @staticmethod
    def _evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        evidence: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            evidence.append(
                evidence_item(
                    f"S{index}-M",
                    str(row["provider"]),
                    f"{row['ticker']} 가격·유동성·분기 재무 스냅샷",
                    row["last_trading_date"],
                    limitations=["yfinance 데이터는 거래소 공식 원장을 대체하지 않습니다."],
                )
            )
            for filing_index, filing in enumerate(row.get("sec_filings") or [], start=1):
                evidence.append(
                    evidence_item(
                        f"S{index}-F{filing_index}",
                        "sec_edgar",
                        f"{row['ticker']} {filing.get('form') or 'SEC filing'}",
                        filing.get("filed_at"),
                        url=filing.get("source_url"),
                        limitations=["공시 문구는 결과의 성공 가능성을 보장하지 않습니다."],
                    )
                )
        return evidence
