from __future__ import annotations

from typing import Any, Mapping

from app.services.advisory.features.common import (
    evidence_item,
    finite_float,
    now_iso,
    percent_change,
    rounded,
    statement_values,
    ticker_snapshot,
)
from app.services.technical_analysis_service import TechnicalAnalysisService


class ProfitTakingReviewService:
    """Independently evaluate a profitable stored position without order execution."""

    def __init__(
        self,
        market_data_service: Any,
        yf_module: Any,
        technical_analysis_service: TechnicalAnalysisService | None = None,
        now_provider: Any | None = None,
    ) -> None:
        self.market_data_service = market_data_service
        self.yf_module = yf_module
        self.technical_analysis_service = technical_analysis_service or TechnicalAnalysisService()
        self.now_provider = now_provider

    def analyze(
        self,
        asset: Mapping[str, Any] | None,
        review_horizon: str,
        *,
        portfolio_total_value: float | None = None,
        currency_fx_rate: float | None = None,
        max_asset_weight_pct: float = 25.0,
        latest_report: Mapping[str, Any] | None = None,
        upcoming_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        generated_at = now_iso(self.now_provider)
        if not isinstance(asset, Mapping):
            return self._unavailable_result(
                generated_at,
                "보유 자산을 찾을 수 없어 저장된 보유분만 대상으로 하는 판단을 제공하지 않습니다.",
                evaluation_status="not_applicable",
            )

        market = str(asset.get("market") or "").upper()
        ticker = str(asset.get("ticker") or "").upper()
        quantity = finite_float(asset.get("quantity"))
        average_price = finite_float(asset.get("avg_price"))
        if (
            market == "CASH"
            or not ticker
            or quantity is None
            or quantity <= 0
            or average_price is None
            or average_price <= 0
        ):
            return self._unavailable_result(
                generated_at,
                "현금·미보유·평균단가 오류 자산은 이익실현 판단 대상이 아닙니다.",
                asset=asset,
                evaluation_status="not_applicable",
            )

        market_data = self.market_data_service.fetch_price_history(market, ticker, 400)
        current_price = finite_float(getattr(market_data, "current_price", None))
        last_trading_date = getattr(market_data, "last_trading_date", None)
        technical = self.technical_analysis_service.analyze(ticker, market_data.dataframe)
        if (
            current_price is None
            or bool(getattr(market_data, "is_stale", True))
            or last_trading_date is None
            or technical.trend_label == "data-limited"
        ):
            return self._unavailable_result(
                generated_at,
                (
                    "최신 시세 또는 120거래일 기술 데이터가 부족하여 "
                    "강한 이익실현 판단을 제공하지 않습니다."
                ),
                asset=asset,
                market_data=market_data,
                evaluation_status="data_limited",
            )

        return_pct = percent_change(current_price, average_price)
        if return_pct is None or return_pct <= 0:
            return self._unavailable_result(
                generated_at,
                "현재 평가수익이 없거나 손실 상태여서 이익실현 전용 판단을 제공하지 않습니다.",
                asset=asset,
                market_data=market_data,
                current_price=current_price,
                evaluation_status="not_applicable",
            )

        position_value_native = quantity * current_price
        asset_currency = str(asset.get("currency") or "").upper()
        uses_usd = (
            market == "US"
            or asset_currency == "USD"
            or (market == "ETF" and asset_currency != "KRW")
        )
        provided_fx_rate = finite_float(currency_fx_rate)
        fx_available = not uses_usd or (provided_fx_rate is not None and provided_fx_rate > 0)
        fx_rate = provided_fx_rate if uses_usd else 1.0
        portfolio_total = finite_float(portfolio_total_value)
        position_weight_pct = (
            position_value_native * fx_rate / portfolio_total * 100
            if portfolio_total is not None
            and portfolio_total > 0
            and fx_available
            and fx_rate is not None
            else None
        )
        fundamentals = self._fundamentals(market, ticker)
        events = list(upcoming_events or [])
        signals = self._signals(technical, current_price)
        scores = self._scores(
            technical.technical_score,
            signals,
            fundamentals,
            return_pct,
            position_weight_pct,
            max_asset_weight_pct,
            events,
        )
        fundamentals_limited = fundamentals["status"] != "available"
        concentration_limited = position_weight_pct is None
        data_limited = fundamentals_limited or concentration_limited
        decision = self._decision(
            scores,
            signals,
            fundamentals,
            data_limited=data_limited,
        )
        decision["primary_reasons"] = self._primary_reasons(
            signals,
            fundamentals,
            scores,
            return_pct,
        )
        position = self._position_snapshot(
            asset,
            current_price,
            return_pct,
            position_value_native,
            position_weight_pct,
            max_asset_weight_pct,
        )
        price_framework = self._price_framework(
            current_price,
            average_price,
            technical,
            review_horizon,
        )
        report_conflict = self._report_conflict(latest_report, decision["action"])
        evidence = self._evidence(
            ticker,
            market_data,
            fundamentals,
            events,
            latest_report,
        )
        limitations = []
        if fundamentals_limited:
            limitations.append(
                "기초 펀더멘털 데이터가 불완전하여 전량 이익실현·추가 노출 판단을 제한했습니다."
            )
        if concentration_limited:
            limitations.append(
                "포트폴리오 총액 또는 환율을 확인하지 못해 집중도를 계산할 수 없으며 "
                "강한 판단을 제한했습니다."
            )
        if not events:
            limitations.append("확인 가능한 향후 실적·배당 일정이 없습니다.")
        if uses_usd:
            limitations.append(
                "평가손익은 자산 통화 기준의 세전·비용 차감 전 값이며 "
                "과거 환전 원가를 반영하지 않습니다."
            )
        return {
            "analysis_type": "profit_taking_review",
            "generated_at": generated_at,
            "position_snapshot": position,
            "decision": decision,
            "scorecard": {
                **scores,
                "technical_score": technical.technical_score,
                "technical_score_breakdown": technical.score_breakdown,
                "fundamentals_available": fundamentals["available"],
                "fundamentals_status": fundamentals["status"],
                "concentration_available": not concentration_limited,
                "data_limited_actions_blocked": ["SELL", "BUY"] if data_limited else [],
            },
            "option_comparison": self._option_comparison(scores, signals, data_limited),
            "price_framework": price_framework,
            "report_conflict": report_conflict,
            "risks": self._risks(
                signals,
                fundamentals,
                position_weight_pct,
                max_asset_weight_pct,
                events,
            ),
            "catalysts": self._catalysts(signals, fundamentals, events),
            "invalidation_conditions": self._invalidation_conditions(
                technical,
                review_horizon,
            ),
            "evidence": evidence,
            "data_quality": {
                "status": "partial" if data_limited else "fresh",
                "limitations": limitations,
                "market_data_status": "fresh",
                "fundamentals_status": fundamentals["status"],
                "concentration_status": (
                    "available" if not concentration_limited else "data-limited"
                ),
                "event_status": "available" if events else "unavailable",
            },
            "evaluation_status": "available" if not data_limited else "partial",
            "summary": decision["one_line_conclusion"],
            "disclaimer": (
                "현재 보유분의 이익 보존과 위험을 독립 재평가한 투자 의사결정 지원 정보이며 "
                "수익을 보장하지 않습니다. 자동매매나 주문을 실행하지 않습니다."
            ),
        }

    def _unavailable_result(
        self,
        generated_at: str,
        reason: str,
        *,
        asset: Mapping[str, Any] | None = None,
        market_data: Any | None = None,
        current_price: float | None = None,
        evaluation_status: str,
    ) -> dict[str, Any]:
        ticker = str((asset or {}).get("ticker") or "").upper() or None
        market = str((asset or {}).get("market") or "").upper() or None
        last_trading_date = getattr(market_data, "last_trading_date", None)
        evidence = []
        if market_data is not None:
            evidence.append(
                evidence_item(
                    "profit-taking-market-data",
                    str(getattr(market_data, "provider", "market_data")),
                    "이익실현 판단용 최신 시세 확인",
                    last_trading_date.isoformat() if last_trading_date else None,
                    limitations=[str(getattr(market_data, "data_quality_note", reason))],
                )
            )
        return {
            "analysis_type": "profit_taking_review",
            "generated_at": generated_at,
            "position_snapshot": {
                "asset_id": (asset or {}).get("id"),
                "ticker": ticker,
                "market": market,
                "quantity": rounded((asset or {}).get("quantity")),
                "average_price": rounded((asset or {}).get("avg_price")),
                "current_price": rounded(current_price),
            },
            "decision": {
                "action": "WATCH",
                "scope": "wait_for_evidence",
                "confidence": 0,
                "one_line_conclusion": reason,
                "decision_reason": [reason],
                "primary_reasons": [reason],
                "independent_from_latest_report": True,
            },
            "scorecard": {
                "hold_support_score": 0,
                "realization_pressure_score": 0,
                "add_support_score": 0,
                "risk_categories": [],
                "data_limited_actions_blocked": ["SELL", "BUY"],
            },
            "option_comparison": self._unavailable_option_comparison(),
            "price_framework": {
                "current_price": rounded(current_price),
                "status": "unavailable",
                "note": "주문가가 아닌 재검토용 관찰 기준이며 최신 데이터가 필요합니다.",
            },
            "report_conflict": self._report_conflict(None, "WATCH"),
            "risks": [{"category": "data_quality", "detail": reason}],
            "catalysts": [],
            "invalidation_conditions": [],
            "evidence": evidence,
            "data_quality": {
                "status": "data-limited",
                "limitations": [reason],
            },
            "evaluation_status": evaluation_status,
            "summary": reason,
            "disclaimer": (
                "투자 의사결정 지원 정보이며 수익을 보장하지 않습니다. "
                "자동매매나 주문을 실행하지 않습니다."
            ),
        }

    def _fundamentals(self, market: str, ticker: str) -> dict[str, Any]:
        if market == "KR":
            return {
                "available": False,
                "has_data": False,
                "available_metric_count": 0,
                "status": "unavailable",
                "reason": "국내 종목 기초 펀더멘털 데이터가 없습니다.",
            }
        try:
            snapshot = ticker_snapshot(self.yf_module, ticker)
        except Exception:
            return {
                "available": False,
                "has_data": False,
                "available_metric_count": 0,
                "status": "unavailable",
                "reason": "기초 펀더멘털 데이터를 수집하지 못했습니다.",
            }
        financials = snapshot["quarterly_financials"]
        cashflow = snapshot["quarterly_cashflow"]
        revenue, previous_revenue = statement_values(
            financials, ("Total Revenue", "Operating Revenue")
        )
        operating_income, previous_operating_income = statement_values(
            financials, ("Operating Income",)
        )
        free_cash_flow, previous_free_cash_flow = statement_values(cashflow, ("Free Cash Flow",))
        margin = self._margin(operating_income, revenue)
        previous_margin = self._margin(previous_operating_income, previous_revenue)
        margin_change = (
            round(margin - previous_margin, 2)
            if margin is not None and previous_margin is not None
            else None
        )
        revenue_growth = percent_change(revenue, previous_revenue)
        free_cash_flow_change = percent_change(free_cash_flow, previous_free_cash_flow)
        info = snapshot["info"]
        available_count = sum(
            value is not None for value in (revenue_growth, margin_change, free_cash_flow_change)
        )
        status = (
            "available" if available_count == 3 else "partial" if available_count else "unavailable"
        )
        return {
            "available": status == "available",
            "has_data": available_count > 0,
            "available_metric_count": available_count,
            "status": status,
            "name": info.get("longName") or ticker,
            "revenue_growth_pct": revenue_growth,
            "operating_margin_change_pct_points": margin_change,
            "free_cash_flow_change_pct": free_cash_flow_change,
            "trailing_pe": rounded(info.get("trailingPE")),
            "forward_pe": rounded(info.get("forwardPE")),
            "reason": (
                None
                if status == "available"
                else "분기 매출·영업이익률·잉여현금흐름 비교 데이터가 일부 또는 전부 부족합니다."
            ),
        }

    @staticmethod
    def _margin(numerator: float | None, denominator: float | None) -> float | None:
        if numerator is None or denominator in {None, 0.0}:
            return None
        return round(numerator / denominator * 100, 2)

    @staticmethod
    def _signals(technical: Any, current_price: float) -> dict[str, Any]:
        indicators = technical.indicators
        rsi = finite_float(indicators.get("rsi_14"))
        macd = finite_float(indicators.get("macd"))
        macd_signal = finite_float(indicators.get("macd_signal"))
        sma_20 = finite_float(indicators.get("sma_20"))
        sma_60 = finite_float(indicators.get("sma_60"))
        bb_upper = finite_float(indicators.get("bb_upper"))
        atr = finite_float(indicators.get("atr_14"))
        return {
            "rsi_14": rsi,
            "macd": macd,
            "macd_signal": macd_signal,
            "sma_20": sma_20,
            "sma_60": sma_60,
            "bb_upper": bb_upper,
            "atr_14": atr,
            "overextended": bool(
                (rsi is not None and rsi >= 72) or (bb_upper and current_price >= bb_upper)
            ),
            "trend_weakening": bool(
                (sma_20 is not None and current_price < sma_20)
                or (macd is not None and macd_signal is not None and macd < macd_signal)
            ),
            "trend_break": bool(
                sma_60 is not None and current_price < sma_60 and technical.technical_score < 50
            ),
        }

    @staticmethod
    def _scores(
        technical_score: int,
        signals: Mapping[str, Any],
        fundamentals: Mapping[str, Any],
        unrealized_return_pct: float,
        position_weight_pct: float | None,
        max_asset_weight_pct: float,
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        concentration_exceeded = (
            position_weight_pct is not None and position_weight_pct >= max_asset_weight_pct
        )
        hold_support = round(min(30.0, technical_score * 0.3))
        if (
            fundamentals.get("revenue_growth_pct") is not None
            and fundamentals["revenue_growth_pct"] > 0
        ):
            hold_support += 8
        if (
            fundamentals.get("operating_margin_change_pct_points") is not None
            and fundamentals["operating_margin_change_pct_points"] > 0
        ):
            hold_support += 7
        if (
            fundamentals.get("free_cash_flow_change_pct") is not None
            and fundamentals["free_cash_flow_change_pct"] > 0
        ):
            hold_support += 5
        forward_pe = finite_float(fundamentals.get("forward_pe"))
        trailing_pe = finite_float(fundamentals.get("trailing_pe"))
        if forward_pe is not None and 0 < forward_pe <= 30:
            hold_support += 6
        elif trailing_pe is not None and 0 < trailing_pe <= 35:
            hold_support += 4
        if not signals["trend_break"]:
            hold_support += 10
        hold_support += 0 if concentration_exceeded else 15

        pressure = 0
        categories = set()
        if signals["trend_weakening"]:
            pressure += 15
            categories.add("trend")
        if signals["trend_break"]:
            pressure += 15
            categories.add("trend")
        if signals["overextended"]:
            pressure += 20
            categories.add("overextension")
        if unrealized_return_pct >= 50:
            pressure += 15
            categories.add("profit_cushion")
        elif unrealized_return_pct >= 25:
            pressure += 10
            categories.add("profit_cushion")
        elif unrealized_return_pct >= 10:
            pressure += 5
            categories.add("profit_cushion")
        if concentration_exceeded:
            pressure += (
                20
                if position_weight_pct and position_weight_pct >= max_asset_weight_pct + 10
                else 15
            )
            categories.add("concentration")
        if any(event.get("event_type") == "earnings" for event in events):
            pressure += 15
            categories.add("event")
        if (forward_pe is not None and forward_pe > 35) or (
            trailing_pe is not None and trailing_pe > 45
        ):
            pressure += 10
            categories.add("valuation")

        add_support = round(min(40.0, technical_score * 0.4))
        if (
            fundamentals.get("revenue_growth_pct") is not None
            and fundamentals["revenue_growth_pct"] > 0
        ):
            add_support += 10
        if (
            fundamentals.get("operating_margin_change_pct_points") is not None
            and fundamentals["operating_margin_change_pct_points"] > 0
        ):
            add_support += 10
        if (
            fundamentals.get("free_cash_flow_change_pct") is not None
            and fundamentals["free_cash_flow_change_pct"] > 0
        ):
            add_support += 10
        add_support += 10 if not signals["overextended"] and not concentration_exceeded else 0
        add_support += 10 if forward_pe is not None and 0 < forward_pe <= 30 else 0
        return {
            "hold_support_score": min(100, int(hold_support)),
            "realization_pressure_score": min(100, int(pressure)),
            "add_support_score": min(100, int(add_support)),
            "risk_categories": sorted(categories),
            "concentration_exceeded": concentration_exceeded,
            "position_weight_pct": rounded(position_weight_pct),
            "max_asset_weight_pct": rounded(max_asset_weight_pct),
            "unrealized_return_pct": rounded(unrealized_return_pct),
        }

    @staticmethod
    def _option_comparison(
        scores: Mapping[str, Any],
        signals: Mapping[str, Any],
        data_limited: bool,
    ) -> list[dict[str, Any]]:
        hold_support = int(scores["hold_support_score"])
        pressure = int(scores["realization_pressure_score"])
        add_support = int(scores["add_support_score"])
        sell_score = pressure if not data_limited else min(pressure, 40)
        reduce_score = min(100, pressure + (15 if scores["concentration_exceeded"] else 0))
        hold_score = max(0, min(100, hold_support - max(0, pressure - 35) // 2))
        buy_score = add_support if not data_limited else min(add_support, 40)
        options = [
            {
                "action": "SELL",
                "suitability_score": sell_score,
                "current_view": "우세" if sell_score >= 75 else "제한",
                "when_it_fits": (
                    "이익실현 압력이 높고 서로 다른 위험군이 함께 확인될 때 검토합니다."
                ),
            },
            {
                "action": "REDUCE",
                "suitability_score": reduce_score,
                "current_view": "우세" if reduce_score >= 55 else "보조",
                "when_it_fits": (
                    "집중도 초과·과열·추세 약화로 일부 이익 보존이 필요할 때 검토합니다."
                ),
            },
            {
                "action": "HOLD",
                "suitability_score": hold_score,
                "current_view": "우세" if hold_score >= 60 and pressure < 55 else "보조",
                "when_it_fits": (
                    "보유 지지가 이익실현 압력보다 우세하고 중기 추세가 유지될 때 검토합니다."
                ),
            },
            {
                "action": "BUY",
                "suitability_score": buy_score,
                "current_view": (
                    "우세"
                    if buy_score >= 80
                    and pressure < 35
                    and not signals["overextended"]
                    and not scores["concentration_exceeded"]
                    else "제한"
                ),
                "when_it_fits": (
                    "추가 노출 지지가 높고 과열·집중도 문제가 없을 때만 "
                    "위험 예산 안에서 검토합니다."
                ),
            },
        ]
        return options

    @staticmethod
    def _unavailable_option_comparison() -> list[dict[str, Any]]:
        return [
            {
                "action": action,
                "suitability_score": 0,
                "current_view": "데이터 부족",
                "when_it_fits": "최신 시세와 기술·기초 데이터가 충족된 뒤 다시 검토합니다.",
            }
            for action in ("SELL", "REDUCE", "HOLD", "BUY")
        ]

    @staticmethod
    def _decision(
        scores: Mapping[str, Any],
        signals: Mapping[str, Any],
        fundamentals: Mapping[str, Any],
        *,
        data_limited: bool,
    ) -> dict[str, Any]:
        hold_support = int(scores["hold_support_score"])
        pressure = int(scores["realization_pressure_score"])
        add_support = int(scores["add_support_score"])
        risk_categories = list(scores["risk_categories"])
        concentration_exceeded = bool(scores["concentration_exceeded"])
        if not data_limited and pressure >= 75 and len(risk_categories) >= 2:
            action, scope, reason = (
                "SELL",
                "full_exit_review",
                "여러 위험군의 이익실현 압력이 높습니다.",
            )
        elif pressure >= 55 or concentration_exceeded or signals["overextended"]:
            action, scope, reason = (
                "REDUCE",
                "partial_profit_taking_review",
                "이익 보존 또는 집중도 관리 필요성이 확인됩니다.",
            )
        elif (
            not data_limited
            and add_support >= 80
            and hold_support >= 70
            and pressure < 35
            and not signals["overextended"]
            and not concentration_exceeded
        ):
            action, scope, reason = (
                "BUY",
                "add_review",
                "추가 노출은 위험 예산 안에서만 검토할 수 있습니다.",
            )
        elif hold_support >= 60 and pressure < 55:
            action, scope, reason = (
                "HOLD",
                "hold_review",
                "추세·기초 지표·집중도를 함께 볼 때 보유 근거가 우세합니다.",
            )
        else:
            action, scope, reason = (
                "WATCH",
                "wait_for_evidence",
                "보유와 이익실현 근거가 엇갈려 추가 확인이 필요합니다.",
            )
        confidence = max(0, min(90, 45 + abs(hold_support - pressure) // 2))
        if data_limited:
            confidence = min(confidence, 65)
        return {
            "action": action,
            "scope": scope,
            "confidence": confidence,
            "one_line_conclusion": reason,
            "decision_reason": [
                (
                    f"보유 지지 점수 {hold_support}, 이익실현 압력 점수 {pressure}, "
                    f"추가 노출 지지 점수 {add_support}"
                ),
                "최근 리포트 액션은 이 결정 점수에 반영하지 않았습니다.",
            ],
            "independent_from_latest_report": True,
        }

    @staticmethod
    def _primary_reasons(
        signals: Mapping[str, Any],
        fundamentals: Mapping[str, Any],
        scores: Mapping[str, Any],
        unrealized_return_pct: float,
    ) -> list[str]:
        reasons = []
        if scores["concentration_exceeded"]:
            reasons.append("현재 보유 비중이 설정된 단일 자산 집중도 기준 이상입니다.")
        if signals["trend_break"]:
            reasons.append("중기 추세 훼손과 약한 기술 점수가 함께 확인됩니다.")
        elif signals["trend_weakening"]:
            reasons.append("단기 이동평균 또는 MACD 기준에서 추세 약화 신호가 확인됩니다.")
        else:
            reasons.append("현재 기술 추세에는 뚜렷한 훼손 신호가 없습니다.")
        if signals["overextended"]:
            reasons.append("RSI 또는 볼린저밴드 기준에서 가격 과열 가능성이 확인됩니다.")
        if fundamentals.get("available"):
            improving = []
            if finite_float(fundamentals.get("revenue_growth_pct")) not in {None, 0.0}:
                if float(fundamentals["revenue_growth_pct"]) > 0:
                    improving.append("매출")
            if finite_float(fundamentals.get("operating_margin_change_pct_points")) not in {
                None,
                0.0,
            }:
                if float(fundamentals["operating_margin_change_pct_points"]) > 0:
                    improving.append("영업이익률")
            if finite_float(fundamentals.get("free_cash_flow_change_pct")) not in {None, 0.0}:
                if float(fundamentals["free_cash_flow_change_pct"]) > 0:
                    improving.append("잉여현금흐름")
            if improving:
                reasons.append(f"최근 분기 {'·'.join(improving)} 개선이 보유 근거를 지지합니다.")
        else:
            reasons.append("기초 펀더멘털 자료가 부족해 전량 매도와 추가 노출 판단을 제한했습니다.")
        if unrealized_return_pct >= 10:
            reasons.append("누적 평가수익이 있어 상승 여력과 이익 보호 필요성을 함께 비교했습니다.")
        return reasons[:4]

    @staticmethod
    def _position_snapshot(
        asset: Mapping[str, Any],
        current_price: float,
        return_pct: float,
        position_value_native: float,
        position_weight_pct: float | None,
        max_asset_weight_pct: float,
    ) -> dict[str, Any]:
        quantity = finite_float(asset.get("quantity")) or 0.0
        average_price = finite_float(asset.get("avg_price")) or 0.0
        return {
            "asset_id": asset.get("id"),
            "ticker": str(asset.get("ticker") or "").upper(),
            "name": asset.get("name") or asset.get("ticker"),
            "market": str(asset.get("market") or "").upper(),
            "currency": asset.get("currency"),
            "profit_basis": "native_currency_gross",
            "costs_included": False,
            "profit_basis_note": (
                "자산 통화 기준의 세전·비용 차감 전 평가손익이며 "
                "과거 환전 원가는 반영하지 않습니다."
            ),
            "quantity": rounded(quantity),
            "average_price": rounded(average_price),
            "current_price": rounded(current_price),
            "unrealized_profit_native": rounded(position_value_native - quantity * average_price),
            "unrealized_return_pct": rounded(return_pct),
            "position_value_native": rounded(position_value_native),
            "position_weight_pct": rounded(position_weight_pct),
            "max_asset_weight_pct": rounded(max_asset_weight_pct),
        }

    @staticmethod
    def _price_framework(
        current_price: float,
        average_price: float,
        technical: Any,
        review_horizon: str,
    ) -> dict[str, Any]:
        indicators = technical.indicators
        atr = finite_float(indicators.get("atr_14"))
        horizon_settings = {
            "short": ("sma_20", 1.0, 2.0),
            "medium": ("sma_60", 2.0, 3.0),
            "long": ("sma_120", 3.0, 4.0),
        }
        trend_key, protection_multiple, upside_multiple = horizon_settings[review_horizon]
        trend_reference = finite_float(indicators.get(trend_key))
        protection = (
            max(average_price, current_price - atr * protection_multiple)
            if atr is not None
            else average_price
        )
        return {
            "current_price": rounded(current_price),
            "profit_protection_reference": rounded(protection),
            "upside_review_reference": (
                rounded(current_price + atr * upside_multiple) if atr is not None else None
            ),
            "trend_invalidation_reference": rounded(trend_reference),
            "trend_reference_indicator": trend_key,
            "atr_protection_multiple": protection_multiple,
            "review_horizon": review_horizon,
            "note": "가격은 주문가가 아닌 관찰·재검토 기준이며 수익을 보장하지 않습니다.",
        }

    @staticmethod
    def _report_conflict(
        latest_report: Mapping[str, Any] | None,
        decision_action: str,
    ) -> dict[str, Any]:
        if not latest_report:
            return {
                "status": "unavailable",
                "conflict_status": "unavailable",
                "report_action": None,
                "action": None,
                "report_confidence": None,
                "confidence": None,
                "report_generated_at": None,
                "generated_at": None,
                "decision_influence": "excluded",
                "note": "비교할 최근 리포트 전략이 없습니다.",
                "conflict_reason": "비교할 최근 리포트 전략이 없습니다.",
            }
        report_action = latest_report.get("action")
        conflict = report_action in {"BUY", "HOLD"} and decision_action in {"SELL", "REDUCE"}
        return {
            "status": "conflict" if conflict else "aligned_or_different_scope",
            "conflict_status": "conflict" if conflict else "aligned_or_different_scope",
            "report_action": report_action,
            "action": report_action,
            "report_confidence": latest_report.get("confidence"),
            "confidence": latest_report.get("confidence"),
            "report_generated_at": latest_report.get("generated_at"),
            "generated_at": latest_report.get("generated_at"),
            "decision_influence": "excluded",
            "note": (
                (
                    "기존 리포트는 신규 진입·전망을, 이번 판단은 현재 보유분의 "
                    "이익 보존과 집중도를 봅니다."
                )
                if conflict
                else "최근 리포트는 사후 비교용이며 결정 점수에는 반영하지 않았습니다."
            ),
            "conflict_reason": (
                "기존 리포트와 이번 보유분 이익실현 판단의 목적이 다릅니다."
                if conflict
                else "최근 리포트는 사후 비교용이며 결정 점수에는 반영하지 않았습니다."
            ),
        }

    @staticmethod
    def _risks(
        signals: Mapping[str, Any],
        fundamentals: Mapping[str, Any],
        position_weight_pct: float | None,
        max_asset_weight_pct: float,
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        risks = []
        if signals["trend_weakening"]:
            risks.append({"category": "trend", "detail": "단기 추세 약화 신호를 확인했습니다."})
        if signals["overextended"]:
            risks.append(
                {
                    "category": "overextension",
                    "detail": "과매수 또는 밴드 상단 확장 신호를 확인했습니다.",
                }
            )
        if position_weight_pct is not None and position_weight_pct >= max_asset_weight_pct:
            risks.append(
                {
                    "category": "concentration",
                    "detail": "설정된 단일 자산 집중도 기준 이상입니다.",
                }
            )
        if not fundamentals.get("available"):
            risks.append({"category": "fundamentals", "detail": fundamentals.get("reason")})
        if any(event.get("event_type") == "earnings" for event in events):
            risks.append(
                {
                    "category": "event",
                    "detail": "향후 실적 발표 전후 변동성 가능성이 있습니다.",
                }
            )
        return risks

    @staticmethod
    def _catalysts(
        signals: Mapping[str, Any],
        fundamentals: Mapping[str, Any],
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        catalysts = []
        if not signals["trend_weakening"]:
            catalysts.append(
                {"category": "trend", "detail": "기술 추세 훼손 신호가 뚜렷하지 않습니다."}
            )
        if (
            fundamentals.get("revenue_growth_pct") is not None
            and fundamentals["revenue_growth_pct"] > 0
        ):
            catalysts.append(
                {"category": "fundamentals", "detail": "최근 분기 매출 성장 지표가 양호합니다."}
            )
        if (
            fundamentals.get("free_cash_flow_change_pct") is not None
            and fundamentals["free_cash_flow_change_pct"] > 0
        ):
            catalysts.append(
                {"category": "cash_flow", "detail": "최근 분기 잉여현금흐름 변화가 양호합니다."}
            )
        if events:
            catalysts.append(
                {"category": "event", "detail": "향후 일정은 재평가 시점으로 활용합니다."}
            )
        return catalysts

    @staticmethod
    def _invalidation_conditions(
        technical: Any,
        review_horizon: str,
    ) -> list[dict[str, Any]]:
        conditions = []
        horizon_keys = {
            "short": ("sma_20", "단기"),
            "medium": ("sma_60", "중기"),
            "long": ("sma_120", "장기"),
        }
        indicator_key, horizon_label = horizon_keys[review_horizon]
        trend_reference = finite_float(technical.indicators.get(indicator_key))
        if trend_reference is not None:
            conditions.append(
                {
                    "type": "trend",
                    "condition": (
                        f"현재가가 {horizon_label} 이동평균 아래에서 약세를 지속하는지 "
                        "재확인합니다."
                    ),
                    "reference_price": rounded(trend_reference),
                    "reference_indicator": indicator_key,
                }
            )
        if technical.technical_score < 50:
            conditions.append(
                {
                    "type": "technical_score",
                    "condition": "기술 점수가 약세 구간을 유지하면 보유 논리를 다시 검토합니다.",
                    "reference_score": technical.technical_score,
                }
            )
        return conditions

    @staticmethod
    def _evidence(
        ticker: str,
        market_data: Any,
        fundamentals: Mapping[str, Any],
        events: list[dict[str, Any]],
        latest_report: Mapping[str, Any] | None,
    ) -> list[dict[str, Any]]:
        last_trading_date = getattr(market_data, "last_trading_date", None)
        evidence = [
            evidence_item(
                "profit-taking-market-data",
                str(getattr(market_data, "provider", "market_data")),
                f"{ticker} 최신 시세·기술 지표",
                last_trading_date.isoformat() if last_trading_date else None,
                limitations=[str(getattr(market_data, "data_quality_note", ""))],
            ),
            evidence_item(
                "profit-taking-portfolio",
                "alphapilot_portfolio",
                f"{ticker} 저장 보유 자산·집중도",
                None,
                limitations=[
                    (
                        "저장된 보유 수량·평균단가를 사용하며 실제 매도 주문이나 "
                        "세금을 계산하지 않습니다."
                    )
                ],
            ),
        ]
        if fundamentals.get("has_data"):
            evidence.append(
                evidence_item(
                    "profit-taking-fundamentals",
                    "yfinance",
                    f"{ticker} 최근 분기 기초 펀더멘털",
                    None,
                )
            )
        if events:
            evidence.append(
                evidence_item(
                    "profit-taking-events",
                    str(events[0].get("provider") or "yfinance"),
                    f"{ticker} 향후 기업 일정",
                    str(events[0].get("date") or "") or None,
                )
            )
        if latest_report:
            evidence.append(
                evidence_item(
                    "profit-taking-report-comparison",
                    "alphapilot_report",
                    f"{ticker} 최근 리포트 전략 비교",
                    str(latest_report.get("generated_at") or "") or None,
                    limitations=["최근 리포트 액션은 이번 결정 점수에 반영하지 않았습니다."],
                )
            )
        return evidence
