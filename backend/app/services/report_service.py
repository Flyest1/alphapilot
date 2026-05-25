from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.config import (
    get_env_application_defaults,
    get_environment_settings,
    resolve_application_settings,
)
from app.db.supabase_client import Repository
from app.models.report import AssetStrategy, MarketSummary, PortfolioSummary, ReportContent
from app.services.ai_provider import AIProvider
from app.services.market_data_service import MarketDataService
from app.services.openai_provider import OpenAIProvider
from app.services.portfolio_service import PortfolioService
from app.services.strategy_service import StrategyService
from app.services.technical_analysis_service import (
    TechnicalAnalysisResult,
    TechnicalAnalysisService,
)
from app.utils.logging import log_external_failure

DISCLAIMER = "이 리포트는 투자 의사결정 지원용이며 자동 매매를 실행하지 않습니다."
MAX_RECOMMENDED_CANDIDATES = 5
CANDIDATE_HORIZON_RULES = {
    "short": {"min_score": 80, "label": "단기 5거래일", "target_days": 5},
    "medium": {"min_score": 75, "label": "중기 20거래일", "target_days": 20},
    "long": {"min_score": 70, "label": "장기 60거래일", "target_days": 60},
}
CANDIDATE_UNIVERSE: dict[str, list[dict[str, str]]] = {
    "domestic": [
        {"market": "KR", "ticker": "005930", "name": "삼성전자", "currency": "KRW"},
        {"market": "KR", "ticker": "000660", "name": "SK하이닉스", "currency": "KRW"},
        {"market": "KR", "ticker": "005380", "name": "현대차", "currency": "KRW"},
        {"market": "KR", "ticker": "035420", "name": "NAVER", "currency": "KRW"},
        {"market": "KR", "ticker": "068270", "name": "셀트리온", "currency": "KRW"},
        {"market": "KR", "ticker": "105560", "name": "KB금융", "currency": "KRW"},
        {"market": "KR", "ticker": "069500", "name": "KODEX 200", "currency": "KRW"},
        {"market": "KR", "ticker": "091160", "name": "KODEX 반도체", "currency": "KRW"},
    ],
    "global": [
        {"market": "US", "ticker": "NVDA", "name": "NVIDIA", "currency": "USD"},
        {"market": "US", "ticker": "MSFT", "name": "Microsoft", "currency": "USD"},
        {"market": "US", "ticker": "AAPL", "name": "Apple", "currency": "USD"},
        {"market": "US", "ticker": "AMZN", "name": "Amazon", "currency": "USD"},
        {"market": "US", "ticker": "GOOGL", "name": "Alphabet", "currency": "USD"},
        {"market": "US", "ticker": "META", "name": "Meta Platforms", "currency": "USD"},
        {"market": "ETF", "ticker": "VOO", "name": "Vanguard S&P 500 ETF", "currency": "USD"},
        {"market": "ETF", "ticker": "QQQ", "name": "Invesco QQQ Trust", "currency": "USD"},
        {"market": "ETF", "ticker": "SMH", "name": "VanEck Semiconductor ETF", "currency": "USD"},
        {"market": "ETF", "ticker": "SCHD", "name": "Schwab US Dividend ETF", "currency": "USD"},
    ],
}


class ReportService:
    def __init__(
        self,
        repository: Repository,
        market_data_service: MarketDataService | None = None,
        technical_analysis_service: TechnicalAnalysisService | None = None,
        strategy_service: StrategyService | None = None,
        ai_provider: AIProvider | None = None,
    ) -> None:
        self.repository = repository
        self.market_data_service = market_data_service or MarketDataService()
        self.technical_analysis_service = technical_analysis_service or TechnicalAnalysisService()
        self.strategy_service = strategy_service or StrategyService()
        self.ai_provider = ai_provider

    def generate_report(self, report_type: str) -> dict[str, Any]:
        app_settings = resolve_application_settings(
            self.repository.get_settings(),
            get_env_application_defaults(),
        )
        all_assets = self.repository.list_assets()
        assets = self._assets_for_report(all_assets, report_type)
        portfolio_summary = PortfolioService(
            self.repository,
            self.market_data_service,
        ).get_summary()
        analysis_rows = self._build_asset_analysis(
            assets,
            app_settings.stale_data_business_days,
            app_settings.risk_profile,
        )
        candidate_rows = self._build_candidate_analysis(
            report_type,
            all_assets,
            app_settings.stale_data_business_days,
            app_settings.risk_profile,
            app_settings.candidate_horizon,
        )
        analysis_rows = analysis_rows + candidate_rows
        index_rows = self._build_index_analysis(report_type, app_settings.stale_data_business_days)
        stale_tickers = [
            row["asset"]["ticker"] for row in analysis_rows if row["market_data"].is_stale
        ]
        technical_strategies = [
            row["strategy"] for row in analysis_rows if row["strategy"].reasoning != "data-limited"
        ]

        content = self._generate_ai_content(
            report_type=report_type,
            app_settings=app_settings.model_dump(),
            portfolio_summary=portfolio_summary.model_dump(),
            analysis_rows=analysis_rows,
            index_rows=index_rows,
            technical_strategies=technical_strategies,
            stale_tickers=stale_tickers,
        )
        if content is None:
            content = self._technical_only_report(
                report_type,
                portfolio_summary.model_dump(),
                index_rows,
                [row["strategy"] for row in analysis_rows],
                stale_tickers,
                app_settings.frontend_timezone,
            )
        else:
            content = self._enforce_stale_rules(content, analysis_rows, stale_tickers)

        saved = self._save_report(content, assets)
        self.backfill_performance_logs()
        saved["content"] = content.model_dump(mode="json")
        return saved

    def backfill_performance_logs(self) -> None:
        try:
            logs = self.repository.list_performance_logs()
            strategies = {row["id"]: row for row in self.repository.list_strategies()}
            for log_row in logs:
                strategy = strategies.get(log_row.get("strategy_id"))
                if not strategy:
                    continue
                self._backfill_log_row(log_row, strategy)
        except Exception as exc:
            log_external_failure("performance_logs", exc, {"operation": "backfill"})

    def _backfill_log_row(self, log_row: dict[str, Any], strategy: dict[str, Any]) -> None:
        ticker = strategy.get("ticker")
        if not ticker:
            return
        market = self._infer_market(ticker)
        result = self.market_data_service.fetch_price_history(market, ticker, lookback_days=90)
        if result.dataframe.empty:
            return
        created_at = self._parse_datetime(strategy.get("created_at") or log_row.get("created_at"))
        if created_at is None:
            return
        future_rows = result.dataframe[result.dataframe.index.date > created_at.date()]
        updates: dict[str, Any] = {}
        base_price = log_row.get("price_at_recommendation") or strategy.get("current_price")
        if base_price is None:
            return
        for days in (1, 5, 20):
            price_field = f"price_after_{days}d"
            return_field = f"return_after_{days}d"
            if log_row.get(price_field) is not None or len(future_rows) < days:
                continue
            price = float(future_rows.iloc[days - 1]["close"])
            updates[price_field] = round(price, 4)
            updates[return_field] = round(
                ((price - float(base_price)) / float(base_price)) * 100, 4
            )
        if updates:
            updates["evaluated_at"] = datetime.now(timezone.utc).isoformat()
            self.repository.update_performance_log(log_row["id"], updates)

    def _generate_ai_content(
        self,
        report_type: str,
        app_settings: dict[str, Any],
        portfolio_summary: dict[str, Any],
        analysis_rows: list[dict[str, Any]],
        index_rows: dict[str, TechnicalAnalysisResult],
        technical_strategies: list[AssetStrategy],
        stale_tickers: list[str],
    ) -> ReportContent | None:
        try:
            provider = self.ai_provider or self._build_ai_provider(app_settings)
        except Exception as exc:
            log_external_failure("openai", exc, {"operation": "build_ai_provider"})
            return None
        prompt = self._prompt(report_type)
        context = {
            "report_type": report_type,
            "settings": app_settings,
            "portfolio_summary": portfolio_summary,
            "market_indices": {key: value.__dict__ for key, value in index_rows.items()},
            "technical_strategies": [
                strategy.model_dump(mode="json") for strategy in technical_strategies
            ],
            "owned_tickers": [
                self._normalize_ticker(asset.get("ticker", ""))
                for asset in self.repository.list_assets()
            ],
            "candidate_tickers": [
                row["asset"]["ticker"] for row in analysis_rows if row["asset"].get("id") is None
            ],
            "candidate_horizon": app_settings.get("candidate_horizon", "medium"),
            "stale_tickers": stale_tickers,
            "generated_at": self._now(app_settings["frontend_timezone"]),
            "asset_context": [
                {
                    "asset": row["asset"],
                    "market_data": {
                        "provider": row["market_data"].provider,
                        "last_trading_date": row["market_data"].last_trading_date,
                        "is_stale": row["market_data"].is_stale,
                        "data_quality_note": row["market_data"].data_quality_note,
                    },
                    "technical_analysis": row["technical_analysis"].__dict__,
                }
                for row in analysis_rows
                if not row["market_data"].is_stale
            ],
            "disclaimer": DISCLAIMER,
        }

        validation_error: ValidationError | None = None
        for attempt in range(2):
            try:
                response = provider.generate_report(prompt, context)
                content = ReportContent.model_validate(response)
                return content
            except ValidationError as exc:
                validation_error = exc
                log_external_failure(
                    "openai",
                    exc,
                    {"operation": "validate_report", "attempt": attempt + 1},
                )
                prompt = f"{prompt}\nValidation error to fix: {exc}"
            except Exception as exc:
                log_external_failure("openai", exc, {"operation": "generate_report"})
                return None

        if validation_error is not None:
            log_external_failure(
                "openai",
                validation_error,
                {"operation": "validation_failed_after_retry"},
            )
        return None

    def _technical_only_report(
        self,
        report_type: str,
        portfolio_summary: dict[str, Any],
        index_rows: dict[str, TechnicalAnalysisResult],
        strategies: list[AssetStrategy],
        stale_tickers: list[str],
        frontend_timezone: str,
    ) -> ReportContent:
        capped_strategies = []
        for strategy in strategies:
            if strategy.reasoning == "data-limited":
                capped_strategies.append(strategy)
            else:
                capped_strategies.append(
                    strategy.model_copy(
                        update={
                            "confidence": min(strategy.confidence, 60),
                            "reasoning": "technical-only fallback (LLM unavailable)",
                        }
                    )
                )

        key_risks = ["AI reasoning unavailable for this report"]
        if stale_tickers:
            key_risks.append(f"stale market data for: {', '.join(stale_tickers)}")

        opportunities = [
            f"{strategy.ticker}: 기술 점수 기준 {self._action_label(strategy.action)} 후보"
            for strategy in capped_strategies
            if strategy.action in {"BUY", "HOLD"} and strategy.confidence > 0
        ]

        return ReportContent(
            report_type=report_type,
            generated_at=self._now(frontend_timezone),
            market_summary=MarketSummary(
                summary=self._index_summary(report_type, index_rows),
                key_indices=[
                    {
                        "name": name,
                        "technical_score": result.technical_score,
                        "trend_label": result.trend_label,
                    }
                    for name, result in index_rows.items()
                ],
                macro_factors=[],
            ),
            portfolio_summary=self._report_portfolio_summary(portfolio_summary),
            key_risks=key_risks,
            opportunities=opportunities,
            asset_strategies=capped_strategies,
            disclaimer=DISCLAIMER,
        )

    def _build_asset_analysis(
        self,
        assets: list[dict[str, Any]],
        stale_data_business_days: int,
        risk_profile: str,
    ) -> list[dict[str, Any]]:
        rows = []
        for asset in assets:
            market_data = self.market_data_service.fetch_price_history(
                asset["market"],
                asset["ticker"],
                stale_data_business_days=stale_data_business_days,
            )
            technical_analysis = self.technical_analysis_service.analyze(
                asset["ticker"],
                market_data.dataframe,
            )
            strategy = self.strategy_service.generate_strategy(
                asset,
                market_data,
                technical_analysis,
                risk_profile,
            )
            rows.append(
                {
                    "asset": asset,
                    "market_data": market_data,
                    "technical_analysis": technical_analysis,
                    "strategy": strategy,
                }
            )
        return rows

    def _build_candidate_analysis(
        self,
        report_type: str,
        all_assets: list[dict[str, Any]],
        stale_data_business_days: int,
        risk_profile: str,
        candidate_horizon: str,
    ) -> list[dict[str, Any]]:
        owned_tickers = {self._normalize_ticker(asset.get("ticker", "")) for asset in all_assets}
        horizon_rule = CANDIDATE_HORIZON_RULES.get(
            candidate_horizon, CANDIDATE_HORIZON_RULES["medium"]
        )
        rows = []
        for asset in self._candidate_assets(report_type):
            if self._normalize_ticker(asset["ticker"]) in owned_tickers:
                continue
            market_data = self.market_data_service.fetch_price_history(
                asset["market"],
                asset["ticker"],
                stale_data_business_days=stale_data_business_days,
            )
            if market_data.is_stale:
                continue
            technical_analysis = self.technical_analysis_service.analyze(
                asset["ticker"],
                market_data.dataframe,
            )
            if technical_analysis.technical_score < horizon_rule["min_score"]:
                continue
            horizon_score = self._candidate_horizon_score(technical_analysis, candidate_horizon)
            if horizon_score < horizon_rule["min_score"]:
                continue
            strategy = self.strategy_service.generate_strategy(
                asset,
                market_data,
                technical_analysis,
                risk_profile,
            )
            if strategy.action not in {"BUY", "HOLD"} or strategy.reasoning == "data-limited":
                continue
            strategy = strategy.model_copy(
                update={
                    "reasoning": (
                        f"보유 외 추가 매수 후보({horizon_rule['label']} 목표): "
                        f"{strategy.reasoning}"
                    ),
                    "risk": (
                        f"신규 진입 후보입니다. 목표 기간은 {horizon_rule['label']}이며, "
                        f"{strategy.risk}"
                    ),
                }
            )
            rows.append(
                {
                    "asset": asset,
                    "market_data": market_data,
                    "technical_analysis": technical_analysis,
                    "strategy": strategy,
                }
            )
        return sorted(
            rows,
            key=lambda row: (
                self._candidate_horizon_score(row["technical_analysis"], candidate_horizon),
                row["strategy"].confidence,
            ),
            reverse=True,
        )[:MAX_RECOMMENDED_CANDIDATES]

    def _candidate_horizon_score(
        self,
        technical_analysis: TechnicalAnalysisResult,
        candidate_horizon: str,
    ) -> float:
        score = float(technical_analysis.technical_score)
        breakdown = technical_analysis.score_breakdown
        indicators = technical_analysis.indicators
        rsi = float(indicators.get("rsi_14") or 0)
        volume_rate = float(indicators.get("volume_change_rate") or 0)

        if candidate_horizon == "short":
            score += (breakdown.get("momentum", 0) * 0.5) + (breakdown.get("volume", 0) * 0.7)
            if 55 <= rsi <= 72:
                score += 5
            if volume_rate > 20:
                score += 3
            return score
        if candidate_horizon == "long":
            score += (breakdown.get("trend", 0) * 0.7) + (breakdown.get("volatility", 0) * 0.4)
            if rsi <= 75:
                score += 3
            return score
        score += (breakdown.get("trend", 0) * 0.4) + (breakdown.get("price_position", 0) * 0.4)
        if 50 <= rsi <= 70:
            score += 3
        return score

    def _build_index_analysis(
        self,
        report_type: str,
        stale_data_business_days: int,
    ) -> dict[str, TechnicalAnalysisResult]:
        results = self.market_data_service.fetch_major_indices(
            report_type,
            stale_data_business_days=stale_data_business_days,
        )
        return {
            name: self.technical_analysis_service.analyze(name, result.dataframe)
            for name, result in results.items()
        }

    def _save_report(self, content: ReportContent, assets: list[dict[str, Any]]) -> dict[str, Any]:
        report = self.repository.create_report(
            {
                "report_type": content.report_type,
                "title": f"{self._report_type_label(content.report_type)} 시장 리포트",
                "summary": content.market_summary.summary,
                "content": content.model_dump(mode="json"),
            }
        )
        assets_by_ticker = {asset["ticker"]: asset for asset in assets}
        for strategy in content.asset_strategies:
            asset = assets_by_ticker.get(strategy.ticker)
            strategy_row = self.repository.create_strategy(
                {
                    "report_id": report["id"],
                    "asset_id": asset["id"] if asset else None,
                    "ticker": strategy.ticker,
                    "name": strategy.name,
                    "action": strategy.action,
                    "confidence": strategy.confidence,
                    "current_price": strategy.current_price,
                    "buy_range_low": strategy.buy_range_low,
                    "buy_range_high": strategy.buy_range_high,
                    "sell_range_low": strategy.sell_range_low,
                    "sell_range_high": strategy.sell_range_high,
                    "target_price": strategy.target_price,
                    "stop_loss": strategy.stop_loss,
                    "reasoning": strategy.reasoning,
                    "risk": strategy.risk,
                    "invalidation_condition": strategy.invalidation_condition,
                }
            )
            self.repository.create_performance_log(
                {
                    "strategy_id": strategy_row["id"],
                    "ticker": strategy.ticker,
                    "action": strategy.action,
                    "price_at_recommendation": strategy.current_price,
                }
            )
        return report

    def _enforce_stale_rules(
        self,
        content: ReportContent,
        analysis_rows: list[dict[str, Any]],
        stale_tickers: list[str],
    ) -> ReportContent:
        by_ticker = {strategy.ticker: strategy for strategy in content.asset_strategies}
        for row in analysis_rows:
            if row["asset"]["ticker"] in stale_tickers or row["asset"]["ticker"] not in by_ticker:
                by_ticker[row["asset"]["ticker"]] = row["strategy"]
        key_risks = list(content.key_risks)
        if stale_tickers:
            risk = f"stale market data for: {', '.join(stale_tickers)}"
            if risk not in key_risks:
                key_risks.append(risk)
        return content.model_copy(
            update={
                "key_risks": key_risks,
                "asset_strategies": list(by_ticker.values()),
                "disclaimer": content.disclaimer or DISCLAIMER,
            }
        )

    def _assets_for_report(
        self, assets: list[dict[str, Any]], report_type: str
    ) -> list[dict[str, Any]]:
        markets = {"KR"} if report_type == "domestic" else {"US", "ETF"}
        return [asset for asset in assets if asset.get("market") in markets]

    def _candidate_assets(self, report_type: str) -> list[dict[str, Any]]:
        return [
            {
                **candidate,
                "id": None,
                "quantity": 0,
                "avg_price": 0,
                "memo": "보유 외 추천 후보",
            }
            for candidate in CANDIDATE_UNIVERSE.get(report_type, [])
        ]

    def _risk_profile(self) -> str:
        settings = resolve_application_settings(
            self.repository.get_settings(),
            get_env_application_defaults(),
        )
        return settings.risk_profile

    def _build_ai_provider(self, app_settings: dict[str, Any]) -> AIProvider:
        if app_settings.get("ai_provider") != "openai":
            raise RuntimeError("unsupported AI provider for MVP")
        env = get_environment_settings()
        return OpenAIProvider(
            api_key=env.openai_api_key,
            model=app_settings["ai_model"],
        )

    def _prompt(self, report_type: str) -> str:
        return (
            f"Generate a {report_type} AlphaPilot report as JSON matching ReportContent exactly. "
            "The root object must contain only report_type, generated_at, market_summary, "
            "portfolio_summary, key_risks, opportunities, asset_strategies, and disclaimer. "
            "Use context.generated_at as generated_at. market_summary must be an object with "
            "summary, key_indices, and macro_factors. portfolio_summary must be an object with "
            "total_market_value, total_return_rate, risk_level, and allocation_comment only. "
            "asset_strategies must use the technical_strategies input shape and must not be named "
            "strategies. Do not add market_view, portfolio_notes, stale_tickers, risk_profile, "
            "total_cost, total_profit_loss, domestic_value, global_value, or cash_value to the "
            "output. Use decision-support language only. Do not include news factors. Include "
            "action, confidence, ranges, target, stop-loss, reasoning, risk, and invalidation "
            "condition for each non-stale strategy. Write user-facing text fields in Korean, "
            "including market_summary.summary, macro_factors, key_risks, opportunities, "
            "reasoning, risk, invalidation_condition, and allocation_comment. Keep schema keys, "
            "ticker symbols, and action enum values in English exactly as required. Do not write "
            "English sentences in user-facing fields unless the field value is a ticker, provider "
            "name, schema key, or action enum. context.candidate_tickers contains non-owned "
            "screened buy candidates. Include them in asset_strategies when they are present, and "
            "make their reasoning clearly say they are 보유 외 추가 매수 후보. "
            "context.candidate_horizon is the target holding/profit-taking horizon for those "
            "candidate ideas."
        )

    def _index_summary(
        self,
        report_type: str,
        index_rows: dict[str, TechnicalAnalysisResult],
    ) -> str:
        if not index_rows:
            return f"{self._report_type_label(report_type)} 시장 기술 데이터가 제한적입니다."
        parts = [
            f"{name} 기술 점수 {result.technical_score} ({self._trend_label(result.trend_label)})"
            for name, result in index_rows.items()
        ]
        return f"{self._report_type_label(report_type)} 시장 기술 요약: " + "; ".join(parts)

    def _report_portfolio_summary(self, summary: dict[str, Any]) -> PortfolioSummary:
        total_value = float(summary.get("total_market_value") or 0)
        total_return = float(summary.get("total_return_rate") or 0)
        allocation = summary.get("asset_allocation") or []
        max_weight = max((float(row.get("weight") or 0) for row in allocation), default=0)
        risk_level = "high" if max_weight > 60 or total_return < -15 else "medium"
        if max_weight < 35 and total_return > -5:
            risk_level = "low"
        return PortfolioSummary(
            total_market_value=total_value,
            total_return_rate=total_return,
            risk_level=risk_level,
            allocation_comment=f"최대 보유 비중은 {max_weight:.2f}%입니다.",
        )

    def _report_type_label(self, report_type: str) -> str:
        return "국내" if report_type == "domestic" else "글로벌"

    def _action_label(self, action: str) -> str:
        return {
            "BUY": "매수",
            "HOLD": "보유",
            "REDUCE": "축소",
            "SELL": "매도",
            "WATCH": "관찰",
        }.get(action, action)

    def _trend_label(self, trend_label: str) -> str:
        return {
            "strong bullish setup": "강한 상승 흐름",
            "bullish but needs confirmation": "상승 우위이나 확인 필요",
            "neutral / watch": "중립 또는 관찰",
            "weak / reduce risk": "약세, 위험 축소 필요",
            "bearish / sell or avoid": "약세, 매도 또는 회피",
            "data-limited": "데이터 제한",
        }.get(trend_label, trend_label)

    def _now(self, frontend_timezone: str) -> str:
        try:
            tz = ZoneInfo(frontend_timezone)
        except Exception:
            tz = timezone.utc
        return datetime.now(tz).isoformat()

    def _infer_market(self, ticker: str) -> str:
        clean = ticker.replace(".KS", "").replace(".KQ", "")
        return "KR" if clean.isdigit() else "US"

    def _normalize_ticker(self, ticker: str) -> str:
        return str(ticker).upper().replace(".KS", "").replace(".KQ", "").strip()

    def _parse_datetime(self, value: Any) -> datetime | None:
        if value is None:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
