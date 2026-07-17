from __future__ import annotations

from typing import Any

import pandas as pd

from app.services.advisory.features.common import (
    data_quality,
    evidence_item,
    finite_float,
    now_iso,
    percent_change,
    price_on_or_after,
    statement_values,
    ticker_snapshot,
)


class PostEarningsOpportunitiesAnalyzer:
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
        lookback_days: int = 14,
    ) -> dict[str, Any]:
        generated_at = now_iso(self.now_provider)
        rows = [
            self._analyze_ticker(ticker.upper(), generated_at, lookback_days)
            for ticker in dict.fromkeys(tickers)
        ]
        ranked = [row for row in rows if row["analysis_status"] == "available"]
        ranked.sort(key=lambda row: (-row["opportunity_score"], row["ticker"]))
        limitations = []
        if self.filing_provider is None:
            limitations.append(
                "공식 실적 발표일·가이던스·경영진 발언 제공자가 없어 해당 항목은 데이터 부족입니다."
            )
        if any(row["analysis_status"] == "data-limited" for row in rows):
            limitations.append(
                "Required earnings, price-reaction, or financial evidence is unavailable."
            )
        return {
            "analysis_type": "post_earnings_opportunities",
            "generated_at": generated_at,
            "rows": rows,
            "rankings": ranked[: max(1, min(limit, 20))],
            "evidence": self._evidence(rows),
            "data_quality": data_quality(rows, limitations),
            "disclaimer": "실적 발표 후 가격 하락은 매수 적합성을 보장하지 않습니다.",
        }

    def _analyze_ticker(
        self,
        ticker: str,
        retrieved_at: str | None = None,
        lookback_days: int = 14,
    ) -> dict[str, Any]:
        release = self._release(ticker, lookback_days)
        market_data = self.market_data_service.fetch_price_history("US", ticker, 180)
        snapshot = ticker_snapshot(self.yf_module, ticker)
        financials = snapshot["quarterly_financials"]
        revenue, previous_revenue = statement_values(
            financials, ("Total Revenue", "Operating Revenue")
        )
        operating_income, previous_operating_income = statement_values(
            financials, ("Operating Income",)
        )
        diluted_eps, previous_diluted_eps = statement_values(
            financials, ("Diluted EPS", "Basic EPS")
        )
        revenue_growth = percent_change(revenue, previous_revenue)
        eps_change = percent_change(diluted_eps, previous_diluted_eps)
        margin = self._margin(operating_income, revenue)
        previous_margin = self._margin(previous_operating_income, previous_revenue)
        margin_change = (
            round(margin - previous_margin, 2)
            if margin is not None and previous_margin is not None
            else None
        )
        event_price = price_on_or_after(market_data, release.get("filed_at"))
        current_price = finite_float(getattr(market_data, "current_price", None))
        post_return = percent_change(current_price, event_price)
        has_financial_evidence = any(
            value is not None for value in (revenue_growth, eps_change, margin_change)
        )
        analysis_available = bool(release.get("filed_at")) and all(
            (
                release.get("provider") == "sec_edgar",
                event_price is not None,
                current_price is not None,
                post_return is not None,
                has_financial_evidence,
                not bool(getattr(market_data, "is_stale", True)),
                getattr(market_data, "last_trading_date", None) is not None,
            )
        )
        score = (
            self._score(post_return, revenue_growth, eps_change, margin_change)
            if analysis_available
            else None
        )
        action = "BUY" if score is not None and score >= 65 else "WATCH"
        interest_range = (
            {"low": round(current_price * 0.95, 2), "high": round(current_price, 2)}
            if current_price is not None and post_return is not None and post_return < 0
            else None
        )
        return {
            "ticker": ticker,
            "name": snapshot["info"].get("longName") or ticker,
            "earnings_release_date": release.get("filed_at"),
            "post_earnings_return_pct": post_return,
            "decline_reason": release.get("decline_reason"),
            "market_disappointment": release.get("market_disappointment"),
            "eps_estimate": release.get("eps_estimate"),
            "reported_eps": release.get("reported_eps"),
            "eps_surprise_pct": release.get("eps_surprise_pct"),
            "quarterly_revenue_growth_pct": revenue_growth,
            "eps_change_pct": eps_change,
            "operating_margin_change_pct_points": margin_change,
            "guidance": release.get("guidance"),
            "management_highlights": release.get("management_highlights") or [],
            "overreaction_case": release.get("overreaction_case"),
            "long_term_rerating_case": release.get("long_term_rerating_case"),
            "opportunity_status": action,
            "opportunity_score": score,
            "action": action,
            "analysis_status": "available" if analysis_available else "data-limited",
            "data_quality_status": "fresh" if analysis_available else "data-limited",
            "interest_price_range": interest_range,
            "key_risks": release.get("key_risks") or [],
            "source_url": release.get("url"),
            "provider": release.get("provider") or "yfinance",
            "last_trading_date": (
                market_data.last_trading_date.isoformat()
                if getattr(market_data, "last_trading_date", None)
                else None
            ),
            "source_as_of": release.get("filed_at")
            or (
                market_data.last_trading_date.isoformat()
                if getattr(market_data, "last_trading_date", None)
                else None
            ),
            "retrieved_at": retrieved_at or now_iso(self.now_provider),
        }

    def _release(self, ticker: str, lookback_days: int) -> dict[str, Any]:
        if self.filing_provider is not None:
            try:
                try:
                    release = (
                        self.filing_provider.get_latest_earnings_release(
                            ticker, lookback_days=lookback_days
                        )
                        or {}
                    )
                except TypeError:
                    release = self.filing_provider.get_latest_earnings_release(ticker) or {}
                if release:
                    return release
            except Exception:
                pass
        return self._yfinance_earnings_event(ticker, lookback_days)

    def _yfinance_earnings_event(self, ticker: str, lookback_days: int) -> dict[str, Any]:
        try:
            company = self.yf_module.Ticker(ticker)
            getter = getattr(company, "get_earnings_dates", None)
            frame = (
                getter(limit=8) if callable(getter) else getattr(company, "earnings_dates", None)
            )
        except Exception:
            return {}
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return {}
        now = pd.Timestamp(now_iso(self.now_provider))
        now = now.tz_convert("UTC") if now.tzinfo else now.tz_localize("UTC")
        cutoff = now - pd.Timedelta(days=lookback_days)
        for index, row in frame.sort_index(ascending=False).iterrows():
            event_at = pd.Timestamp(index)
            if event_at.tzinfo:
                event_at = event_at.tz_convert("UTC")
            else:
                event_at = event_at.tz_localize("UTC")
            if event_at > now or event_at < cutoff:
                continue
            estimate = finite_float(row.get("EPS Estimate"))
            reported = finite_float(row.get("Reported EPS"))
            surprise = finite_float(row.get("Surprise(%)"))
            disappointment = None
            if estimate is not None and reported is not None and reported < estimate:
                disappointment = "yfinance 집계 EPS가 시장 예상치를 하회했습니다."
            return {
                "filed_at": event_at.date().isoformat(),
                "provider": "yfinance_earnings_calendar",
                "decline_reason": disappointment,
                "market_disappointment": disappointment,
                "guidance": None,
                "management_highlights": [],
                "overreaction_case": None,
                "long_term_rerating_case": None,
                "key_risks": [],
                "eps_estimate": estimate,
                "reported_eps": reported,
                "eps_surprise_pct": surprise,
            }
        return {}

    @staticmethod
    def _margin(income: float | None, revenue: float | None) -> float | None:
        if income is None or revenue in {None, 0.0}:
            return None
        return round(income / revenue * 100, 2)

    @staticmethod
    def _score(
        post_return: float | None,
        revenue_growth: float | None,
        eps_change: float | None,
        margin_change: float | None,
    ) -> int:
        points = 0.0
        if post_return is not None and post_return < 0:
            points += min(abs(post_return) * 1.5, 25)
        if revenue_growth is not None and revenue_growth > 0:
            points += min(revenue_growth, 15)
        if eps_change is not None and eps_change > 0:
            points += min(eps_change / 2, 15)
        if margin_change is not None and margin_change > 0:
            points += min(margin_change * 2, 10)
        return max(0, min(int(round(points)), 100))

    @staticmethod
    def _evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            evidence_item(
                f"E{index}",
                str(row["provider"]),
                f"{row['ticker']} 실적·가격 반응",
                row["earnings_release_date"] or row["last_trading_date"],
                url=row["source_url"],
            )
            for index, row in enumerate(rows, start=1)
        ]
