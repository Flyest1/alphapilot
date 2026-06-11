from typing import Any

from app.models.report import AssetStrategy
from app.utils.labels import risk_profile_label, trend_label


class StrategyService:
    def generate_strategy(
        self,
        asset: dict[str, Any],
        market_data: Any,
        technical_analysis: Any,
        risk_profile: str,
        fallback_mode: bool = False,
    ) -> AssetStrategy:
        ticker = str(asset.get("ticker", ""))
        name = str(asset.get("name", ticker))
        if asset.get("market") == "CASH":
            return AssetStrategy(
                ticker=ticker,
                name=name,
                current_price=float(asset.get("avg_price") or 0),
                action="HOLD",
                confidence=50,
                reasoning="현금성 자산이라 시장 데이터 조회를 건너뜁니다.",
                risk="현금 비중은 하락 위험을 낮출 수 있지만 상승 참여를 제한할 수 있습니다.",
                invalidation_condition="현금 비중 목표가 바뀌면 전략을 다시 검토합니다.",
            )

        if (
            getattr(market_data, "is_stale", True)
            or getattr(market_data, "current_price", None) is None
        ):
            return AssetStrategy(
                ticker=ticker,
                name=name,
                current_price=None,
                action="WATCH",
                confidence=0,
                reasoning="data-limited",
                risk="시장 데이터가 지연되었거나 사용할 수 없습니다.",
                invalidation_condition="최신 시장 데이터가 확보되면 다시 판단합니다.",
            )

        current_price = float(market_data.current_price)
        score = int(getattr(technical_analysis, "technical_score", 0))
        action = self._action_for_score(score, risk_profile)
        confidence = (
            min(score, 60) if fallback_mode else self._confidence_for_profile(score, risk_profile)
        )
        stop_pct = self._stop_loss_pct(risk_profile)
        range_pct = self._range_pct(risk_profile)
        target_pct = self._target_pct(risk_profile, action)
        trend_text = trend_label(getattr(technical_analysis, "trend_label", "watch"))
        reasoning = (
            "technical-only fallback (LLM unavailable)"
            if fallback_mode
            else f"기술 점수 {score}: {trend_text}"
        )

        buy_low = current_price * (1 - range_pct)
        buy_high = current_price * (1 + range_pct / 2)
        sell_low = current_price * (1 - range_pct / 2)
        sell_high = current_price * (1 + range_pct)

        return AssetStrategy(
            ticker=ticker,
            name=name,
            current_price=round(current_price, 4),
            action=action,
            confidence=confidence,
            buy_range_low=round(buy_low, 4) if action in {"BUY", "HOLD", "WATCH"} else None,
            buy_range_high=round(buy_high, 4) if action in {"BUY", "HOLD", "WATCH"} else None,
            sell_range_low=round(sell_low, 4) if action in {"REDUCE", "SELL"} else None,
            sell_range_high=round(sell_high, 4) if action in {"REDUCE", "SELL"} else None,
            target_price=round(current_price * (1 + target_pct), 4),
            stop_loss=round(current_price * (1 - stop_pct), 4),
            reasoning=reasoning,
            risk=self._risk_text(risk_profile, score),
            invalidation_condition=self._invalidation_condition(action, current_price, stop_pct),
        )

    def _action_for_score(self, score: int, risk_profile: str) -> str:
        if score < 35:
            return "SELL"
        if score < 50:
            return "REDUCE"
        if score < 65:
            return "WATCH"
        if score < 80:
            return "BUY" if risk_profile == "aggressive" else "HOLD"
        if risk_profile == "conservative":
            return "HOLD"
        return "BUY"

    def _confidence_for_profile(self, score: int, risk_profile: str) -> int:
        adjustment = {"conservative": -5, "balanced": 0, "aggressive": 5}.get(risk_profile, 0)
        return max(0, min(100, score + adjustment))

    def _stop_loss_pct(self, risk_profile: str) -> float:
        return {"conservative": 0.05, "balanced": 0.08, "aggressive": 0.12}.get(risk_profile, 0.08)

    def _range_pct(self, risk_profile: str) -> float:
        return {"conservative": 0.015, "balanced": 0.025, "aggressive": 0.04}.get(
            risk_profile, 0.025
        )

    def _target_pct(self, risk_profile: str, action: str) -> float:
        if action in {"REDUCE", "SELL"}:
            return 0.03
        return {"conservative": 0.08, "balanced": 0.12, "aggressive": 0.18}.get(risk_profile, 0.12)

    def _risk_text(self, risk_profile: str, score: int) -> str:
        risk_label = risk_profile_label(risk_profile)
        if score < 50:
            return f"{risk_label} 성향: 약한 기술적 흐름이므로 하락 위험 관리가 필요합니다."
        return f"{risk_label} 성향: 포지션 크기와 손절 기준을 지키는 것이 중요합니다."

    def _invalidation_condition(self, action: str, current_price: float, stop_pct: float) -> str:
        if action in {"BUY", "HOLD", "WATCH"}:
            invalidation_price = current_price * (1 - stop_pct)
            return f"종가가 {invalidation_price:.4f} 아래로 내려가면 무효화합니다."
        return "기술 점수가 50을 회복하고 모멘텀이 개선되면 판단을 다시 검토합니다."
