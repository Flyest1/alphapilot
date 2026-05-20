from typing import Any

from app.models.report import AssetStrategy


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
                reasoning="cash reserve; no market data fetch",
                risk="cash allocation can reduce upside participation",
                invalidation_condition="cash allocation target changes",
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
                risk="market data is stale or unavailable",
                invalidation_condition="fresh market data becomes available",
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
        reasoning = (
            "technical-only fallback (LLM unavailable)"
            if fallback_mode
            else f"technical score {score}: {getattr(technical_analysis, 'trend_label', 'watch')}"
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
        if score < 50:
            return f"{risk_profile} profile: weak technical setup requires downside control"
        return f"{risk_profile} profile: use position sizing and stop-loss discipline"

    def _invalidation_condition(self, action: str, current_price: float, stop_pct: float) -> str:
        if action in {"BUY", "HOLD", "WATCH"}:
            invalidation_price = current_price * (1 - stop_pct)
            return f"close below {invalidation_price:.4f}"
        return "technical score recovers above 50 with improving momentum"
