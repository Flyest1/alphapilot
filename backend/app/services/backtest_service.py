"""Offline rule backtest for technical score-to-action mappings.

This is a historical simulation for decision support. It does not place or model orders.
"""

from datetime import datetime, timezone
from typing import Any

from app.db.supabase_client import Repository
from app.services.market_data_service import MarketDataService
from app.services.technical_analysis_service import TechnicalAnalysisService
from app.utils.logging import log_external_failure

SIMULATION_DISCLAIMER = (
    "과거 가격 기반 규칙 시뮬레이션이며 실제 체결, 수수료, 세금, 슬리피지를 반영하지 않습니다. "
    "미래 수익을 보장하지 않습니다."
)


def action_for_score(score: int) -> str:
    if score >= 80:
        return "BUY"
    if score >= 50:
        return "WATCH"
    if score >= 35:
        return "REDUCE"
    return "SELL"


class RuleBacktestService:
    def __init__(
        self,
        repository: Repository,
        market_data_service: MarketDataService,
        technical_analysis_service: TechnicalAnalysisService | None = None,
    ) -> None:
        self.repository = repository
        self.market_data_service = market_data_service
        self.technical_analysis_service = technical_analysis_service or TechnicalAnalysisService()

    def run(
        self,
        report_type: str,
        limit: int = 12,
        forward_days: int = 20,
        sample_step: int = 20,
    ) -> dict[str, Any]:
        universe = self.repository.list_candidate_universe(report_type)[: max(1, min(limit, 30))]
        samples = []
        tested_tickers = []
        for asset in universe:
            try:
                result = self.market_data_service.fetch_price_history(
                    asset["market"],
                    asset["ticker"],
                    lookback_days=520,
                )
                ticker_samples = self._samples_for_frame(
                    asset,
                    result.dataframe,
                    forward_days=forward_days,
                    sample_step=sample_step,
                )
            except Exception as exc:
                log_external_failure(
                    "backtest",
                    exc,
                    {"operation": "run_ticker", "ticker": asset.get("ticker")},
                )
                continue
            if ticker_samples:
                tested_tickers.append(asset["ticker"])
                samples.extend(ticker_samples)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "report_type": report_type,
            "forward_days": forward_days,
            "sample_step": sample_step,
            "tickers_tested": tested_tickers,
            "sample_count": len(samples),
            "groups": self._groups(samples),
            "disclaimer": SIMULATION_DISCLAIMER,
        }

    def _samples_for_frame(
        self,
        asset: dict[str, Any],
        frame: Any,
        forward_days: int,
        sample_step: int,
    ) -> list[dict[str, Any]]:
        if frame is None or frame.empty or len(frame) < 120 + forward_days:
            return []
        rows = []
        for index in range(119, len(frame) - forward_days, sample_step):
            history = frame.iloc[: index + 1]
            result = self.technical_analysis_service.analyze(asset["ticker"], history)
            current_price = float(frame.iloc[index]["close"])
            future_price = float(frame.iloc[index + forward_days]["close"])
            forward_return = ((future_price - current_price) / current_price) * 100
            action = action_for_score(result.technical_score)
            success = None
            if action == "BUY":
                success = forward_return > 0
            elif action in {"REDUCE", "SELL"}:
                success = forward_return <= 0
            rows.append(
                {
                    "ticker": asset["ticker"],
                    "date": str(frame.index[index].date()),
                    "score": result.technical_score,
                    "action": action,
                    "forward_return": forward_return,
                    "success": success,
                }
            )
        return rows

    def _groups(self, samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for sample in samples:
            action = sample["action"]
            group = grouped.setdefault(action, {"returns": [], "directional": []})
            group["returns"].append(float(sample["forward_return"]))
            if sample["success"] is not None:
                group["directional"].append(bool(sample["success"]))
        rows = []
        for action, values in grouped.items():
            returns = values["returns"]
            directional = values["directional"]
            rows.append(
                {
                    "action": action,
                    "sample_count": len(returns),
                    "avg_forward_return": round(sum(returns) / len(returns), 4),
                    "directional_sample_count": len(directional),
                    "directional_success_rate": (
                        round(sum(directional) / len(directional), 4) if directional else None
                    ),
                }
            )
        return sorted(rows, key=lambda row: (-row["sample_count"], row["action"]))
