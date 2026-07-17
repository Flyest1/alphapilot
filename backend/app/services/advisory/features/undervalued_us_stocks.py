from __future__ import annotations

from statistics import median
from typing import Any

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
    valuation_score,
)


class UndervaluedUSStocksAnalyzer:
    _MIN_HISTORICAL_PE_SAMPLES = 3

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

    def analyze(
        self,
        tickers: list[str],
        limit: int = 5,
        min_market_cap_usd: int | None = None,
    ) -> dict[str, Any]:
        generated_at = now_iso(self.now_provider)
        rows = [
            self._analyze_ticker(ticker.upper(), generated_at) for ticker in dict.fromkeys(tickers)
        ]
        candidates = [
            row
            for row in rows
            if row["analysis_status"] == "available"
            and (
                min_market_cap_usd is None
                or (
                    row["market_cap_usd"] is not None
                    and row["market_cap_usd"] >= min_market_cap_usd
                )
            )
        ]
        candidates.sort(key=lambda row: (-row["investment_score"], row["ticker"]))
        limitations = [
            "공식 회사 가이던스가 제공되지 않으면 해당 항목은 데이터 부족으로 표시됩니다.",
            "과거 평균 밸류에이션은 point-in-time 재무 이력이 없으면 비교하지 않습니다.",
            "분석 범위는 요청에 포함된 티커로 제한됩니다.",
        ]
        return {
            "analysis_type": "undervalued_us_stocks",
            "generated_at": generated_at,
            "investment_horizon": "6-18 months",
            "rows": rows,
            "top_candidates": candidates[: max(1, min(limit, 20))],
            "evidence": self._evidence(rows),
            "data_quality": data_quality(rows, limitations),
            "disclaimer": "투자 의사결정 지원 정보이며 수익을 보장하지 않습니다.",
        }

    def _analyze_ticker(self, ticker: str, retrieved_at: str | None = None) -> dict[str, Any]:
        market_data = self.market_data_service.fetch_price_history("US", ticker, 120)
        snapshot = ticker_snapshot(self.yf_module, ticker)
        info = snapshot["info"]
        official_release = self._official_release(ticker)
        historical_valuation = self._historical_valuation_comparison(ticker, info)
        financials = snapshot["quarterly_financials"]
        cashflow = snapshot["quarterly_cashflow"]
        balance_sheet = snapshot["quarterly_balance_sheet"]
        revenue, previous_revenue = statement_values(
            financials, ("Total Revenue", "Operating Revenue")
        )
        operating_income, previous_operating_income = statement_values(
            financials, ("Operating Income",)
        )
        free_cash_flow, previous_free_cash_flow = statement_values(cashflow, ("Free Cash Flow",))
        cash, _ = statement_values(
            balance_sheet,
            ("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"),
        )
        debt, _ = statement_values(balance_sheet, ("Total Debt",))
        equity, _ = statement_values(
            balance_sheet, ("Stockholders Equity", "Total Equity Gross Minority Interest")
        )
        revenue_growth = percent_change(revenue, previous_revenue)
        margin = self._margin(operating_income, revenue)
        previous_margin = self._margin(previous_operating_income, previous_revenue)
        margin_change = (
            round(margin - previous_margin, 2)
            if margin is not None and previous_margin is not None
            else None
        )
        fcf_change = percent_change(free_cash_flow, previous_free_cash_flow)
        debt_to_equity = (
            round(debt / equity * 100, 2)
            if debt is not None and equity not in {None, 0.0}
            else finite_float(info.get("debtToEquity"))
        )
        three_month_return = period_return(market_data, 66)
        valuation_metrics = (
            info.get("trailingPE"),
            info.get("forwardPE"),
            info.get("priceToBook"),
            info.get("enterpriseToEbitda"),
        )
        has_market_evidence = (
            three_month_return is not None
            and not bool(getattr(market_data, "is_stale", True))
            and getattr(market_data, "last_trading_date", None) is not None
        )
        has_valuation_evidence = any(finite_float(value) is not None for value in valuation_metrics)
        has_fundamental_evidence = any(
            value is not None
            for value in (revenue_growth, margin, fcf_change, debt_to_equity, cash)
        )
        analysis_available = (
            has_market_evidence
            and has_valuation_evidence
            and has_fundamental_evidence
            and historical_valuation is not None
        )
        score = (
            self._score(
                three_month_return,
                revenue_growth,
                margin_change,
                fcf_change,
                debt_to_equity,
                cash,
                valuation_score(info),
            )
            if analysis_available
            else None
        )
        action = "BUY" if score is not None and score >= 65 else "WATCH"
        last_trading_date = (
            market_data.last_trading_date.isoformat()
            if getattr(market_data, "last_trading_date", None)
            else None
        )
        return {
            "ticker": ticker,
            "name": info.get("longName") or info.get("shortName") or ticker,
            "three_month_return_pct": three_month_return,
            "quarterly_revenue_growth_pct": revenue_growth,
            "operating_margin_pct": margin,
            "operating_margin_change_pct_points": margin_change,
            "free_cash_flow_change_pct": fcf_change,
            "debt_to_equity_pct": rounded(debt_to_equity),
            "cash": rounded(cash, 0),
            "market_cap_usd": rounded(info.get("marketCap"), 0),
            "guidance": official_release.get("guidance") or "회사 공식 가이던스 데이터 없음",
            "guidance_provider": official_release.get("provider"),
            "guidance_source_url": official_release.get("url"),
            "guidance_as_of": official_release.get("filed_at"),
            "trailing_pe": rounded(info.get("trailingPE")),
            "forward_pe": rounded(info.get("forwardPE")),
            "price_to_book": rounded(info.get("priceToBook")),
            "enterprise_to_ebitda": rounded(info.get("enterpriseToEbitda")),
            "historical_valuation_comparison": historical_valuation,
            "historical_valuation_status": (
                historical_valuation["status"]
                if historical_valuation is not None
                else "data-limited"
            ),
            "market_risk": None,
            "company_profile": info.get("longBusinessSummary"),
            "investment_score": score,
            "investment_appeal_10": round(score / 10, 1) if score is not None else None,
            "action": action,
            "analysis_status": "available" if analysis_available else "data-limited",
            "data_quality_status": "fresh" if analysis_available else "data-limited",
            "provider": getattr(market_data, "provider", "yfinance"),
            "last_trading_date": last_trading_date,
            "source_as_of": last_trading_date,
            "retrieved_at": retrieved_at or now_iso(self.now_provider),
            "is_stale": bool(getattr(market_data, "is_stale", True)),
        }

    def _official_release(self, ticker: str) -> dict[str, Any]:
        if self.filing_provider is None:
            return {}
        try:
            return self.filing_provider.get_latest_earnings_release(ticker) or {}
        except Exception:
            return {}

    @staticmethod
    def _margin(income: float | None, revenue: float | None) -> float | None:
        if income is None or revenue in {None, 0.0}:
            return None
        return round(income / revenue * 100, 2)

    @staticmethod
    def _score(
        price_return: float | None,
        revenue_growth: float | None,
        margin_change: float | None,
        fcf_change: float | None,
        debt_to_equity: float | None,
        cash: float | None,
        valuation_points: float,
    ) -> int:
        points = valuation_points * 10
        if price_return is not None and price_return < 0:
            points += min(abs(price_return), 25)
        if revenue_growth is not None and revenue_growth > 0:
            points += min(revenue_growth, 15)
        if margin_change is not None and margin_change > 0:
            points += min(margin_change * 2, 10)
        if fcf_change is not None and fcf_change > 0:
            points += min(fcf_change / 2, 10)
        if debt_to_equity is not None and debt_to_equity < 100:
            points += 5
        if cash is not None and cash > 0:
            points += 5
        return max(0, min(int(round(points)), 100))

    def _historical_valuation_comparison(
        self, ticker: str, info: dict[str, Any]
    ) -> dict[str, Any] | None:
        current_trailing_pe = finite_float(info.get("trailingPE"))
        if current_trailing_pe is None or current_trailing_pe <= 0:
            return None

        annual_financials = self._annual_financials(ticker)
        historical_prices = self.market_data_service.fetch_price_history("US", ticker, 1260)
        if (
            bool(getattr(historical_prices, "is_stale", True))
            or getattr(historical_prices, "last_trading_date", None) is None
        ):
            return None
        samples = self._historical_pe_samples(annual_financials, historical_prices)
        if len(samples) < self._MIN_HISTORICAL_PE_SAMPLES:
            return None

        historical_pes = sorted(sample["price_to_reported_annual_eps"] for sample in samples)
        median_pe = median(historical_pes)
        comparison_pct = round((current_trailing_pe / median_pe - 1) * 100, 2)
        if comparison_pct <= -10:
            relative_valuation = "below_historical_median"
        elif comparison_pct >= 10:
            relative_valuation = "above_historical_median"
        else:
            relative_valuation = "near_historical_median"

        return {
            "status": "available_with_limitations",
            "current_trailing_pe": rounded(current_trailing_pe),
            "current_forward_pe": rounded(info.get("forwardPE")),
            "historical_price_to_reported_annual_eps_median": rounded(median_pe),
            "historical_price_to_reported_annual_eps_range": {
                "low": rounded(historical_pes[0]),
                "high": rounded(historical_pes[-1]),
            },
            "current_trailing_pe_vs_historical_median_pct": comparison_pct,
            "relative_valuation": relative_valuation,
            "sample_size": len(samples),
            "samples": samples,
            "methodology": (
                "Compares current trailing P/E with historical closing prices divided by "
                "reported annual diluted EPS."
            ),
            "limitations": [
                "Historical price-to-reported-annual-EPS values are not point-in-time and may "
                "contain look-ahead bias because annual results were reported after "
                "fiscal period end.",
                "Current forward P/E is shown without a historical comparison because yfinance "
                "does not provide a reliable historical estimate series here.",
                "This comparison is context only and is not used in the investment score.",
            ],
        }

    def _annual_financials(self, ticker: str) -> pd.DataFrame:
        try:
            company = self.yf_module.Ticker(ticker)
            for attribute in ("financials", "income_stmt"):
                financials = getattr(company, attribute, None)
                if isinstance(financials, pd.DataFrame) and not financials.empty:
                    return financials
        except Exception:
            return pd.DataFrame()
        return pd.DataFrame()

    @staticmethod
    def _historical_pe_samples(
        annual_financials: pd.DataFrame, historical_prices: Any
    ) -> list[dict[str, Any]]:
        frame = getattr(historical_prices, "dataframe", None)
        if (
            not isinstance(annual_financials, pd.DataFrame)
            or annual_financials.empty
            or not isinstance(frame, pd.DataFrame)
            or frame.empty
            or "close" not in frame
        ):
            return []
        label_lookup = {str(index).casefold(): index for index in annual_financials.index}
        eps_row = next(
            (
                label_lookup.get(label.casefold())
                for label in ("Diluted EPS", "Basic EPS")
                if label.casefold() in label_lookup
            ),
            None,
        )
        if eps_row is None:
            return []

        closes = pd.to_numeric(frame["close"], errors="coerce").dropna()
        samples = []
        for period_end in sorted(annual_financials.columns, reverse=True):
            eps = finite_float(annual_financials.loc[eps_row, period_end])
            price = UndervaluedUSStocksAnalyzer._price_on_or_before(closes, period_end)
            if eps is None or eps <= 0 or price is None or price <= 0:
                continue
            samples.append(
                {
                    "fiscal_period_end": pd.Timestamp(period_end).date().isoformat(),
                    "closing_price": rounded(price),
                    "reported_annual_eps": rounded(eps),
                    "price_to_reported_annual_eps": rounded(price / eps),
                }
            )
        return samples

    @staticmethod
    def _price_on_or_before(closes: pd.Series, date_value: Any) -> float | None:
        try:
            target = pd.Timestamp(date_value).tz_localize(None)
            eligible = closes.loc[closes.index <= target]
        except (TypeError, ValueError):
            return None
        return finite_float(eligible.iloc[-1]) if not eligible.empty else None

    @staticmethod
    def _evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            evidence_item(
                f"U{index}",
                str(row["provider"]),
                f"{row['ticker']} 가격·분기 재무 스냅샷",
                row["last_trading_date"],
                limitations=["가이던스와 과거 평균 밸류에이션은 별도 공식 자료가 필요합니다."],
            )
            for index, row in enumerate(rows, start=1)
        ]
