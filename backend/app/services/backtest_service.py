"""재현 가능한 기술 규칙 백테스트와 위험조정 성과 검증."""

from collections import defaultdict
from datetime import datetime, timezone
from math import ceil
from types import SimpleNamespace
from typing import Any

import pandas as pd

from app.config import get_env_application_defaults, resolve_application_settings
from app.db.supabase_client import Repository
from app.services.backtest_metrics import (
    calculate_backtest_metrics,
    estimate_round_trip_cost_pct,
)
from app.services.backtest_validation import (
    aggregate_validation_results,
    calculate_baseline_returns,
    classify_market_regime,
    create_walk_forward_folds,
)
from app.services.market_data_service import MarketDataService
from app.services.report.tracking import evaluate_barriers, horizon_days
from app.services.strategy_service import StrategyService
from app.services.technical_analysis_service import TechnicalAnalysisService
from app.utils.logging import log_external_failure

STRATEGY_VERSION = "2026-07-phase1-v1"
SLIPPAGE_MODEL_VERSION = "krw-notional-buckets-v1"
SIMULATION_DISCLAIMER = (
    "과거 가격 기반 규칙 시뮬레이션이며 수수료·세금·환전비와 보수적 슬리피지를 "
    "추정 반영합니다. 실제 체결이나 주문을 모델링하지 않으며 미래 수익을 보장하지 않습니다."
)
BASELINE_LABELS = {
    "buy_and_hold": "단순 보유",
    "sma_trend": "SMA 추세",
    "simple_momentum": "단순 모멘텀",
}


def action_for_score(score: int, risk_profile: str = "balanced") -> str:
    return StrategyService.action_for_score(score, risk_profile)


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
        self.strategy_service = StrategyService()

    def run(
        self,
        report_type: str,
        limit: int = 12,
        forward_days: int | None = None,
        sample_step: int = 20,
        risk_profile: str | None = None,
    ) -> dict[str, Any]:
        app_settings = resolve_application_settings(
            self.repository.get_settings(),
            get_env_application_defaults(),
        )
        resolved_risk_profile = risk_profile or app_settings.risk_profile
        resolved_forward_days = forward_days or horizon_days(app_settings.candidate_horizon)
        resolved_sample_step = max(sample_step, resolved_forward_days)
        universe = self.repository.list_candidate_universe(report_type)[: max(1, min(limit, 30))]
        samples: list[dict[str, Any]] = []
        tested_tickers = []
        liquidity_missing = 0
        data_sources = []
        for asset in universe:
            try:
                result = self.market_data_service.fetch_price_history(
                    asset["market"],
                    asset["ticker"],
                    lookback_days=760,
                )
                ticker_samples = self._samples_for_frame(
                    asset,
                    result.dataframe,
                    forward_days=resolved_forward_days,
                    sample_step=resolved_sample_step,
                    risk_profile=resolved_risk_profile,
                    app_settings=app_settings,
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
                data_sources.append(
                    {
                        "ticker": asset["ticker"],
                        "market": asset.get("market"),
                        "provider": result.provider,
                        "data_start": str(result.dataframe.index.min().date()),
                        "data_end": str(result.dataframe.index.max().date()),
                    }
                )
                liquidity_missing += sum(
                    1 for sample in ticker_samples if sample["average_trading_value"] is None
                )
                samples.extend(ticker_samples)

        samples.sort(key=lambda row: (row["date"], row["ticker"]))
        portfolio_samples = self._daily_portfolio_samples(samples)
        metric_samples = self._non_overlapping_samples(portfolio_samples)
        metrics = calculate_backtest_metrics(metric_samples)
        signal_activity = calculate_backtest_metrics(samples)
        metrics["recommendation_frequency"] = signal_activity["recommendation_frequency"]
        metrics["aggregation"] = "equal_weight_by_decision_date"
        metrics["cohort_count"] = len(metric_samples)
        baselines = self._baseline_summaries(samples)
        buy_hold = next(
            (row for row in baselines if row["name"] == "buy_and_hold"),
            None,
        )
        net_cumulative = metrics["net"]["cumulative_return_pct"]
        benchmark_cumulative = (
            buy_hold["metrics"]["net"]["cumulative_return_pct"] if buy_hold else 0.0
        )
        metrics["excess_return_pct"] = round(net_cumulative - benchmark_cumulative, 6)
        walk_forward = self._walk_forward_summary(
            metric_samples,
            resolved_forward_days,
            resolved_sample_step,
        )
        validation_groups = aggregate_validation_results(
            [
                {
                    **sample,
                    "net_return": sample["net_return_pct"] / 100,
                }
                for sample in samples
            ]
        )
        regime_groups = self._regime_groups(validation_groups)
        market_results = self._market_results(
            samples,
            resolved_forward_days,
            resolved_sample_step,
        )
        bias_warnings = [
            "현재 후보 유니버스를 과거에도 그대로 사용하므로 생존편향 가능성이 있습니다.",
            "누적·연환산 성과는 액션 방향을 정규화한 동일가중 신호 바스켓이며 "
            "실제 포트폴리오 수익률이 아닙니다.",
        ]
        if liquidity_missing:
            bias_warnings.append(
                f"{liquidity_missing}개 표본은 거래대금이 없어 보수적 기본 슬리피지를 적용했습니다."
            )
        if walk_forward["fold_count"] < 2:
            bias_warnings.append("워크포워드 외부 평가 fold가 부족해 안정성 판단이 제한됩니다.")

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "report_type": report_type,
            "strategy_version": STRATEGY_VERSION,
            "settings_snapshot": {
                "risk_profile": resolved_risk_profile,
                "candidate_horizon": app_settings.candidate_horizon,
                "forward_days": resolved_forward_days,
                "sample_step": resolved_sample_step,
                "fee_rate_pct": app_settings.fee_rate_pct,
                "kr_tax_rate_pct": app_settings.kr_tax_rate_pct,
                "fx_spread_pct": app_settings.fx_spread_pct,
                "usd_krw_rate": app_settings.usd_krw_rate,
            },
            "input_snapshot": {
                "limit": limit,
                "universe": [
                    {
                        "ticker": row.get("ticker"),
                        "market": row.get("market"),
                        "currency": row.get("currency"),
                        "source": row.get("source"),
                        "source_rank": row.get("source_rank"),
                    }
                    for row in universe
                ],
                "data_sources": data_sources,
                "as_of": max((row["data_end"] for row in data_sources), default=None),
                "slippage_model_version": SLIPPAGE_MODEL_VERSION,
                "entry_timing": "next_trading_day_open_or_close_fallback",
                "return_aggregation": "equal_weight_by_decision_date",
            },
            "forward_days": resolved_forward_days,
            "sample_step": resolved_sample_step,
            "tickers_tested": tested_tickers,
            "sample_count": len(samples),
            "groups": self._groups(samples),
            "metrics": metrics,
            "costs": self._average_costs(samples),
            "baselines": baselines,
            "walk_forward": walk_forward,
            "validation_groups": validation_groups,
            "regime_groups": regime_groups,
            "market_results": market_results,
            "metric_definitions": {
                "sortino": "MAR 0%, 전체 평가기간의 음수 편차를 사용",
                "annualized_return": "날짜별 동일가중 신호 바스켓의 평가기간 연환산 수익률",
                "recovery_days": "이전 고점을 회복하지 못한 경우 null",
            },
            "bias_warnings": bias_warnings,
            "disclaimer": SIMULATION_DISCLAIMER,
        }

    def _samples_for_frame(
        self,
        asset: dict[str, Any],
        frame: Any,
        forward_days: int,
        sample_step: int,
        risk_profile: str,
        app_settings: Any,
    ) -> list[dict[str, Any]]:
        if frame is None or frame.empty or len(frame) < 120 + forward_days:
            return []
        rows = []
        for index in range(119, len(frame) - forward_days, sample_step):
            history = frame.iloc[: index + 1]
            result = self.technical_analysis_service.analyze(asset["ticker"], history)
            entry_index = index + 1
            entry_column = "open" if "open" in frame else "close"
            entry_price = float(frame.iloc[entry_index][entry_column])
            future_price = float(frame.iloc[index + forward_days]["close"])
            strategy = self.strategy_service.generate_strategy(
                asset,
                SimpleNamespace(is_stale=False, current_price=entry_price),
                result,
                risk_profile,
            )
            future_rows = frame.iloc[index + 1 : index + forward_days + 1]
            barrier_result = evaluate_barriers(
                strategy.action,
                strategy.target_price,
                strategy.stop_loss,
                future_rows,
            )
            outcome_status = barrier_result[0] if barrier_result else "expired"
            barrier_hit_at = barrier_result[1] if barrier_result else None
            exit_price = self._exit_price(
                strategy,
                outcome_status,
                future_price,
            )
            gross_return_pct = self._directional_return_pct(
                strategy.action,
                entry_price,
                exit_price,
            )
            average_trading_value = self._average_trading_value(history, asset, app_settings)
            cost_market = self._cost_market(asset)
            cost = estimate_round_trip_cost_pct(
                action=strategy.action,
                market=cost_market,
                fee_rate_pct=app_settings.fee_rate_pct,
                kr_tax_rate_pct=app_settings.kr_tax_rate_pct,
                fx_spread_pct=app_settings.fx_spread_pct,
                average_trading_value=average_trading_value,
            )
            baselines = calculate_baseline_returns(frame, index, forward_days)
            turnover = self._action_turnover(strategy.action)
            applied_cost_pct = self._applied_cost_pct(strategy.action, cost)
            rows.append(
                {
                    "ticker": asset["ticker"],
                    "market": asset.get("market") or "UNKNOWN",
                    "date": str(frame.index[index].date()),
                    "entry_date": str(frame.index[entry_index].date()),
                    "label_end_date": str(frame.index[index + forward_days].date()),
                    "entry_price": entry_price,
                    "horizon_price": future_price,
                    "score": result.technical_score,
                    "action": strategy.action,
                    "regime": classify_market_regime(frame, index),
                    "gross_return_pct": self._bounded_return(gross_return_pct),
                    "net_return_pct": self._bounded_return(gross_return_pct - applied_cost_pct),
                    "forward_return": round(
                        ((future_price - entry_price) / entry_price) * 100,
                        6,
                    ),
                    "target_price": strategy.target_price,
                    "stop_loss": strategy.stop_loss,
                    "outcome_status": outcome_status,
                    "barrier_hit_at": barrier_hit_at,
                    "success": outcome_status == "hit_target",
                    "cost": cost,
                    "applied_cost_pct": round(applied_cost_pct, 6),
                    "average_trading_value": average_trading_value,
                    "baselines": {
                        key: value * 100
                        for key, value in baselines.items()
                        if key in BASELINE_LABELS
                    },
                    "baseline_directions": {
                        "buy_and_hold": 1,
                        "sma_trend": baselines["sma_direction"],
                        "simple_momentum": baselines["momentum_direction"],
                    },
                    "turnover": turnover,
                    "exposure_assumption": self._exposure_assumption(strategy.action),
                }
            )
        return rows

    def _groups(self, samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for sample in samples:
            action = sample["action"]
            group = grouped.setdefault(
                action,
                {"forward": [], "gross": [], "net": [], "directional": []},
            )
            group["forward"].append(float(sample["forward_return"]))
            group["gross"].append(float(sample["gross_return_pct"]))
            group["net"].append(float(sample["net_return_pct"]))
            group["directional"].append(bool(sample["success"]))
        rows = []
        for action, values in grouped.items():
            rows.append(
                {
                    "action": action,
                    "sample_count": len(values["forward"]),
                    "avg_forward_return": self._average(values["forward"]),
                    "avg_gross_return_pct": self._average(values["gross"]),
                    "avg_net_return_pct": self._average(values["net"]),
                    "directional_sample_count": len(values["directional"]),
                    "directional_success_rate": self._average(values["directional"]),
                }
            )
        return sorted(rows, key=lambda row: (-row["sample_count"], row["action"]))

    def _baseline_summaries(self, samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for name, label in BASELINE_LABELS.items():
            baseline_samples = []
            by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for sample in samples:
                by_ticker[sample["ticker"]].append(sample)
            for ticker_samples in by_ticker.values():
                ticker_samples.sort(key=lambda row: row["date"])
                previous_direction = 0
                previous_mark_price = None
                for index, sample in enumerate(ticker_samples):
                    direction = int(sample["baseline_directions"][name])
                    turnover = abs(direction - previous_direction)
                    is_last = index == len(ticker_samples) - 1
                    if is_last:
                        turnover += abs(direction)
                    tax_events = int(previous_direction != 0 and direction != previous_direction)
                    tax_events += int(is_last and direction != 0)
                    applied_cost = self._baseline_cost_pct(
                        sample["cost"],
                        turnover,
                        tax_events,
                    )
                    gross_return = float(sample["baselines"][name])
                    if previous_direction == direction and previous_mark_price is not None:
                        raw_return = (
                            float(sample["horizon_price"]) / previous_mark_price - 1
                        ) * 100
                        gross_return = direction * raw_return
                    baseline_samples.append(
                        {
                            "date": sample["date"],
                            "label_end_date": sample["label_end_date"],
                            "gross_return_pct": self._bounded_return(gross_return),
                            "net_return_pct": self._bounded_return(gross_return - applied_cost),
                            "turnover": turnover,
                        }
                    )
                    previous_direction = direction
                    previous_mark_price = float(sample["horizon_price"])
            daily_samples = self._daily_portfolio_samples(baseline_samples)
            metric_samples = self._non_overlapping_samples(daily_samples)
            baseline_metrics = calculate_backtest_metrics(metric_samples)
            activity = calculate_backtest_metrics(baseline_samples)
            baseline_metrics["turnover"] = activity["turnover"]
            rows.append(
                {
                    "name": name,
                    "label": label,
                    "metrics": baseline_metrics,
                }
            )
        return rows

    def _walk_forward_summary(
        self,
        samples: list[dict[str, Any]],
        forward_days: int,
        sample_step: int,
    ) -> dict[str, Any]:
        sample_count = len(samples)
        train_size = max(10, sample_count // 2)
        test_size = max(5, sample_count // 5)
        embargo_samples = max(1, ceil(forward_days / sample_step))
        validation = create_walk_forward_folds(
            samples,
            train_size=train_size,
            test_size=test_size,
            forward_days=embargo_samples,
        )
        folds = []
        for fold in validation["folds"]:
            test_samples = [samples[index] for index in fold["test_indices"]]
            fold_metrics = calculate_backtest_metrics(test_samples)
            folds.append(
                {
                    "fold": fold["fold"],
                    "train_count": len(fold["train_indices"]),
                    "purged_count": len(fold["purged_indices"]),
                    "test_count": len(test_samples),
                    "test_start_date": fold["test_start_date"],
                    "test_end_date": fold["test_end_date"],
                    "metrics": fold_metrics,
                }
            )
        fold_returns = [fold["metrics"]["net"]["cumulative_return_pct"] for fold in folds]
        stability_warning = None
        if len(folds) < 2:
            stability_warning = validation["reason"] or "외부 평가 fold가 2개 미만입니다."
        elif any(value <= 0 for value in fold_returns):
            stability_warning = "일부 외부 평가 fold의 비용 차감 누적수익률이 0 이하입니다."
        return {
            "fold_count": len(folds),
            "embargo_samples": embargo_samples,
            "folds": folds,
            "reason": validation["reason"],
            "stability_warning": stability_warning,
        }

    def _regime_groups(self, validation_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for row in validation_groups:
            grouped[row["regime"]].append((row["sample_count"], row["avg_net_return"]))
        results = []
        for regime, values in sorted(grouped.items()):
            count = sum(value[0] for value in values)
            weighted_return = sum(value[0] * value[1] for value in values) / count
            results.append(
                {
                    "regime": regime,
                    "sample_count": count,
                    "avg_net_return_pct": round(weighted_return * 100, 6),
                }
            )
        return results

    def _average_costs(self, samples: list[dict[str, Any]]) -> dict[str, float]:
        keys = ("fee_pct", "kr_tax_pct", "fx_spread_pct", "slippage_pct", "total_cost_pct")
        return {key: self._average([sample["cost"][key] for sample in samples]) for key in keys}

    def _daily_portfolio_samples(self, samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for sample in samples:
            grouped[str(sample["date"])].append(sample)
        rows = []
        for decision_date, date_samples in sorted(grouped.items()):
            rows.append(
                {
                    "date": decision_date,
                    "label_end_date": max(
                        str(sample.get("label_end_date") or decision_date)
                        for sample in date_samples
                    ),
                    "gross_return_pct": self._average(
                        [sample["gross_return_pct"] for sample in date_samples]
                    ),
                    "net_return_pct": self._average(
                        [sample["net_return_pct"] for sample in date_samples]
                    ),
                    "turnover": self._average(
                        [sample.get("turnover", 0) for sample in date_samples]
                    ),
                }
            )
        return rows

    def _non_overlapping_samples(self, samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected = []
        prior_label_end = None
        for sample in sorted(samples, key=lambda row: row["date"]):
            decision_date = str(sample["date"])
            if prior_label_end is not None and decision_date < prior_label_end:
                continue
            selected.append(sample)
            prior_label_end = str(sample.get("label_end_date") or decision_date)
        return selected

    def _market_results(
        self,
        samples: list[dict[str, Any]],
        forward_days: int,
        sample_step: int,
    ) -> list[dict[str, Any]]:
        rows = []
        for market in sorted({str(sample["market"]) for sample in samples}):
            market_samples = [sample for sample in samples if sample["market"] == market]
            daily_samples = self._daily_portfolio_samples(market_samples)
            metric_samples = self._non_overlapping_samples(daily_samples)
            rows.append(
                {
                    "market": market,
                    "sample_count": len(market_samples),
                    "metrics": calculate_backtest_metrics(metric_samples),
                    "baselines": self._baseline_summaries(market_samples),
                    "walk_forward": self._walk_forward_summary(
                        metric_samples,
                        forward_days,
                        sample_step,
                    ),
                }
            )
        return rows

    def _average_trading_value(self, history: pd.DataFrame, asset: dict[str, Any], settings: Any):
        if "volume" not in history or history["volume"].tail(20).isna().all():
            return None
        values = history["close"].tail(20) * history["volume"].tail(20)
        average = float(values.mean())
        if str(asset.get("currency") or "").upper() == "USD":
            average *= float(settings.usd_krw_rate)
        return average if pd.notna(average) else None

    def _cost_market(self, asset: dict[str, Any]) -> str:
        market = str(asset.get("market") or "").upper()
        if market == "ETF" and str(asset.get("currency") or "").upper() == "KRW":
            return "KR"
        return market

    def _exit_price(self, strategy: Any, outcome_status: str, future_price: float) -> float:
        if outcome_status == "hit_target" and strategy.target_price is not None:
            return float(strategy.target_price)
        if outcome_status in {"hit_stop", "ambiguous"} and strategy.stop_loss is not None:
            return float(strategy.stop_loss)
        return future_price

    def _directional_return_pct(self, action: str, entry_price: float, exit_price: float) -> float:
        raw_return = ((exit_price - entry_price) / entry_price) * 100
        directional_return = -raw_return if action in {"SELL", "REDUCE"} else raw_return
        return self._bounded_return(directional_return)

    def _action_turnover(self, action: str) -> float:
        return {"BUY": 2.0, "SELL": 1.0, "REDUCE": 1.0, "HOLD": 0.0, "WATCH": 0.0}.get(
            action,
            0.0,
        )

    def _applied_cost_pct(self, action: str, cost: dict[str, float]) -> float:
        if action == "BUY":
            return float(cost["total_cost_pct"])
        if action in {"SELL", "REDUCE"}:
            return round(
                float(cost["fee_pct"]) / 2
                + float(cost["kr_tax_pct"])
                + float(cost["fx_spread_pct"]) / 2
                + float(cost["slippage_pct"]) / 2,
                6,
            )
        return 0.0

    def _baseline_cost_pct(
        self,
        cost: dict[str, float],
        turnover: float,
        tax_events: int,
    ) -> float:
        return round(
            (float(cost["fee_pct"]) + float(cost["fx_spread_pct"]) + float(cost["slippage_pct"]))
            * turnover
            / 2
            + float(cost["kr_tax_pct"]) * tax_events,
            6,
        )

    def _exposure_assumption(self, action: str) -> str:
        if action == "BUY":
            return "hypothetical_long_round_trip"
        if action in {"SELL", "REDUCE"}:
            return "avoided_loss_directional_score_with_one_way_cost"
        return "observation_only_no_transaction_cost"

    def _bounded_return(self, value: float) -> float:
        return round(max(float(value), -99.999999), 6)

    def _average(self, values: list[Any]) -> float:
        return round(sum(float(value) for value in values) / len(values), 6) if values else 0.0
