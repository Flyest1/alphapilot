from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
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
from app.services.news_service import NewsService
from app.services.openai_provider import OpenAIProvider
from app.services.portfolio_service import PortfolioService
from app.services.report_job_service import ReportJobStore
from app.services.strategy_service import StrategyService
from app.services.technical_analysis_service import (
    TechnicalAnalysisResult,
    TechnicalAnalysisService,
)
from app.utils.datetime import parse_iso_datetime
from app.utils.logging import log_external_failure

DISCLAIMER = "이 리포트는 투자 의사결정 지원용이며 자동 매매를 실행하지 않습니다."
MAX_RECOMMENDED_CANDIDATES = 10
RECOMMENDATION_PRICE_CHANGE_THRESHOLD = 0.05
CANDIDATE_HORIZON_RULES = {
    "short": {"min_score": 68, "label": "단기 5거래일", "target_days": 5},
    "medium": {"min_score": 64, "label": "중기 20거래일", "target_days": 20},
    "long": {"min_score": 60, "label": "장기 60거래일", "target_days": 60},
}
CANDIDATE_UNIVERSE: dict[str, list[dict[str, str]]] = {
    "domestic": [
        {"market": "KR", "ticker": "005930", "name": "삼성전자", "currency": "KRW"},
        {"market": "KR", "ticker": "000660", "name": "SK하이닉스", "currency": "KRW"},
        {"market": "KR", "ticker": "005380", "name": "현대차", "currency": "KRW"},
        {"market": "KR", "ticker": "000270", "name": "Kia", "currency": "KRW"},
        {"market": "KR", "ticker": "035420", "name": "NAVER", "currency": "KRW"},
        {"market": "KR", "ticker": "035720", "name": "Kakao", "currency": "KRW"},
        {"market": "KR", "ticker": "068270", "name": "셀트리온", "currency": "KRW"},
        {"market": "KR", "ticker": "105560", "name": "KB금융", "currency": "KRW"},
        {"market": "KR", "ticker": "055550", "name": "Shinhan Financial", "currency": "KRW"},
        {"market": "KR", "ticker": "006400", "name": "Samsung SDI", "currency": "KRW"},
        {"market": "KR", "ticker": "051910", "name": "LG Chem", "currency": "KRW"},
        {"market": "KR", "ticker": "012450", "name": "Hanwha Aerospace", "currency": "KRW"},
        {"market": "KR", "ticker": "064350", "name": "Hyundai Rotem", "currency": "KRW"},
        {"market": "KR", "ticker": "034020", "name": "Doosan Enerbility", "currency": "KRW"},
        {"market": "KR", "ticker": "069500", "name": "KODEX 200", "currency": "KRW"},
        {"market": "KR", "ticker": "091160", "name": "KODEX 반도체", "currency": "KRW"},
        {"market": "KR", "ticker": "305720", "name": "KODEX Battery", "currency": "KRW"},
        {"market": "KR", "ticker": "360750", "name": "TIGER US S&P500", "currency": "KRW"},
        {"market": "KR", "ticker": "133690", "name": "TIGER NASDAQ100", "currency": "KRW"},
    ],
    "global": [
        {"market": "US", "ticker": "NVDA", "name": "NVIDIA", "currency": "USD"},
        {"market": "US", "ticker": "MSFT", "name": "Microsoft", "currency": "USD"},
        {"market": "US", "ticker": "AAPL", "name": "Apple", "currency": "USD"},
        {"market": "US", "ticker": "AMZN", "name": "Amazon", "currency": "USD"},
        {"market": "US", "ticker": "GOOGL", "name": "Alphabet", "currency": "USD"},
        {"market": "US", "ticker": "META", "name": "Meta Platforms", "currency": "USD"},
        {"market": "US", "ticker": "TSLA", "name": "Tesla", "currency": "USD"},
        {"market": "US", "ticker": "AVGO", "name": "Broadcom", "currency": "USD"},
        {"market": "US", "ticker": "AMD", "name": "AMD", "currency": "USD"},
        {"market": "US", "ticker": "NFLX", "name": "Netflix", "currency": "USD"},
        {"market": "US", "ticker": "COST", "name": "Costco", "currency": "USD"},
        {"market": "US", "ticker": "JPM", "name": "JPMorgan Chase", "currency": "USD"},
        {"market": "US", "ticker": "LLY", "name": "Eli Lilly", "currency": "USD"},
        {"market": "US", "ticker": "V", "name": "Visa", "currency": "USD"},
        {"market": "US", "ticker": "BRK.B", "name": "Berkshire Hathaway", "currency": "USD"},
        {"market": "ETF", "ticker": "VOO", "name": "Vanguard S&P 500 ETF", "currency": "USD"},
        {"market": "ETF", "ticker": "SPY", "name": "SPDR S&P 500 ETF", "currency": "USD"},
        {"market": "ETF", "ticker": "QQQ", "name": "Invesco QQQ Trust", "currency": "USD"},
        {"market": "ETF", "ticker": "SMH", "name": "VanEck Semiconductor ETF", "currency": "USD"},
        {"market": "ETF", "ticker": "SCHD", "name": "Schwab US Dividend ETF", "currency": "USD"},
        {
            "market": "ETF",
            "ticker": "VTI",
            "name": "Vanguard Total Stock Market ETF",
            "currency": "USD",
        },
        {"market": "ETF", "ticker": "IWM", "name": "iShares Russell 2000 ETF", "currency": "USD"},
        {
            "market": "ETF",
            "ticker": "XLK",
            "name": "Technology Select Sector SPDR",
            "currency": "USD",
        },
        {"market": "ETF", "ticker": "GLD", "name": "SPDR Gold Shares", "currency": "USD"},
        {
            "market": "ETF",
            "ticker": "TLT",
            "name": "iShares 20+ Year Treasury Bond ETF",
            "currency": "USD",
        },
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
        news_service: NewsService | None = None,
        report_job_store: ReportJobStore | None = None,
        report_job_id: str | None = None,
    ) -> None:
        self.repository = repository
        self.market_data_service = market_data_service or MarketDataService()
        self.technical_analysis_service = technical_analysis_service or TechnicalAnalysisService()
        self.strategy_service = strategy_service or StrategyService()
        self.ai_provider = ai_provider
        self.news_service = news_service or NewsService()
        self.report_job_store = report_job_store
        self.report_job_id = report_job_id

    def generate_report(self, report_type: str) -> dict[str, Any]:
        with self._timed_step("settings"):
            app_settings = resolve_application_settings(
                self.repository.get_settings(),
                get_env_application_defaults(),
            )
            app_settings = self._refresh_usd_krw_rate(app_settings)
            all_assets = self.repository.list_assets()
            assets = self._assets_for_report(all_assets, report_type)
        with self._timed_step("portfolio"):
            portfolio_summary = PortfolioService(
                self.repository,
                self.market_data_service,
            ).get_summary()
        with self._timed_step("owned_asset_analysis"):
            analysis_rows = self._build_asset_analysis(
                assets,
                app_settings.stale_data_business_days,
                app_settings.risk_profile,
            )
        with self._timed_step("candidate_analysis"):
            candidate_rows = self._build_candidate_analysis(
                report_type,
                all_assets,
                app_settings.stale_data_business_days,
                app_settings.risk_profile,
                app_settings.candidate_horizon,
            )
        analysis_rows = analysis_rows + candidate_rows
        with self._timed_step("market_indices"):
            index_rows = self._build_index_analysis(
                report_type, app_settings.stale_data_business_days
            )
        stale_tickers = [
            row["asset"]["ticker"] for row in analysis_rows if row["market_data"].is_stale
        ]
        technical_strategies = [
            row["strategy"] for row in analysis_rows if row["strategy"].reasoning != "data-limited"
        ]
        with self._timed_step("news_context"):
            news_context = self._build_news_context(
                report_type,
                [row["asset"] for row in analysis_rows if not row["market_data"].is_stale],
            )

        with self._timed_step("ai_report"):
            content = self._generate_ai_content(
                report_type=report_type,
                app_settings=app_settings.model_dump(),
                portfolio_summary=portfolio_summary.model_dump(),
                analysis_rows=analysis_rows,
                index_rows=index_rows,
                technical_strategies=technical_strategies,
                stale_tickers=stale_tickers,
                news_context=news_context,
            )
        if content is None:
            content = self._technical_only_report(
                report_type,
                portfolio_summary.model_dump(),
                index_rows,
                [row["strategy"] for row in analysis_rows],
                stale_tickers,
                app_settings.frontend_timezone,
                news_context,
            )
        else:
            content = self._enforce_stale_rules(content, analysis_rows, stale_tickers)
        content = self._append_news_context_note(content, news_context)

        with self._timed_step("save_report"):
            saved = self._save_report(
                content,
                assets,
                app_settings.candidate_horizon,
                portfolio_summary.model_dump(mode="json"),
                app_settings.frontend_timezone,
            )
        with self._timed_step("performance_backfill"):
            self.backfill_performance_logs()
        with self._timed_step("recommendation_backfill"):
            self.backfill_recommendation_cycles()
        saved["content"] = content.model_dump(mode="json")
        return saved

    def _timed_step(self, step_name: str) -> Any:
        if self.report_job_store is None or not self.report_job_id:
            return nullcontext()
        return self.report_job_store.time_step(self.report_job_id, step_name)

    def backfill_performance_logs(self) -> None:
        try:
            logs = self.repository.list_performance_logs(limit=250)
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
        created_at = parse_iso_datetime(strategy.get("created_at") or log_row.get("created_at"))
        if created_at is None:
            return
        today = datetime.now(timezone.utc).date()
        future_rows = result.dataframe[
            (result.dataframe.index.date > created_at.date())
            & (result.dataframe.index.date <= today)
        ]
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

    def backfill_recommendation_cycles(self) -> None:
        try:
            cycles = self.repository.list_recommendation_cycles(limit=500)
            for cycle in cycles:
                self._backfill_cycle_row(cycle)
        except Exception as exc:
            log_external_failure("recommendation_cycles", exc, {"operation": "backfill"})

    def _backfill_cycle_row(self, cycle: dict[str, Any]) -> None:
        ticker = cycle.get("ticker")
        if not ticker:
            return
        market = self._infer_market(ticker)
        result = self.market_data_service.fetch_price_history(market, ticker, lookback_days=160)
        if result.dataframe.empty:
            return
        started_at = parse_iso_datetime(cycle.get("started_at") or cycle.get("created_at"))
        if started_at is None:
            return
        today = datetime.now(timezone.utc).date()
        future_rows = result.dataframe[
            (result.dataframe.index.date > started_at.date())
            & (result.dataframe.index.date <= today)
        ]
        if future_rows.empty:
            return
        reference_price = cycle.get("reference_price")
        if reference_price is None:
            return
        reference_price = float(reference_price)
        updates: dict[str, Any] = {}
        for days in (1, 5, 20, 60):
            price_field = f"price_after_{days}d"
            return_field = f"return_after_{days}d"
            if cycle.get(price_field) is not None or len(future_rows) < days:
                continue
            price = float(future_rows.iloc[days - 1]["close"])
            updates[price_field] = round(price, 4)
            updates[return_field] = round(((price - reference_price) / reference_price) * 100, 4)

        if cycle.get("status") == "active":
            terminal_status = self._cycle_terminal_status(cycle, future_rows)
            if terminal_status:
                updates["status"] = terminal_status
                updates["closed_at"] = datetime.now(timezone.utc).isoformat()
            elif len(future_rows) >= self._horizon_days(cycle.get("horizon")):
                updates["status"] = "expired"
                updates["closed_at"] = datetime.now(timezone.utc).isoformat()

        if updates:
            updates["evaluated_at"] = datetime.now(timezone.utc).isoformat()
            self.repository.update_recommendation_cycle(cycle["id"], updates)

    def _cycle_terminal_status(
        self,
        cycle: dict[str, Any],
        future_rows: Any,
    ) -> str | None:
        target = cycle.get("target_price")
        stop = cycle.get("stop_loss")
        target_price = float(target) if target is not None else None
        stop_loss = float(stop) if stop is not None else None
        if target_price is None and stop_loss is None:
            return None
        for _, row in future_rows.iterrows():
            high = float(row.get("high", row.get("close")))
            low = float(row.get("low", row.get("close")))
            if stop_loss is not None and low <= stop_loss:
                return "hit_stop"
            if target_price is not None and high >= target_price:
                return "hit_target"
        return None

    def _horizon_days(self, horizon: Any) -> int:
        return {
            "short": 5,
            "medium": 20,
            "long": 60,
        }.get(str(horizon or "medium"), 20)

    def _generate_ai_content(
        self,
        report_type: str,
        app_settings: dict[str, Any],
        portfolio_summary: dict[str, Any],
        analysis_rows: list[dict[str, Any]],
        index_rows: dict[str, TechnicalAnalysisResult],
        technical_strategies: list[AssetStrategy],
        stale_tickers: list[str],
        news_context: dict[str, Any],
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
            "news_context": news_context,
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
        news_context: dict[str, Any] | None = None,
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
        if news_context and news_context.get("status") == "unavailable":
            key_risks.append("recent news context unavailable for this report")

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
        return self._build_analysis_rows(assets, stale_data_business_days, risk_profile)

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
        candidate_assets = [
            asset
            for asset in self._candidate_assets(report_type)
            if self._normalize_ticker(asset["ticker"]) not in owned_tickers
        ]
        rows = []
        for row in self._build_analysis_rows(
            candidate_assets,
            stale_data_business_days,
            risk_profile,
        ):
            asset = row["asset"]
            market_data = row["market_data"]
            technical_analysis = row["technical_analysis"]
            strategy = row["strategy"]
            if self._normalize_ticker(asset["ticker"]) in owned_tickers:
                continue
            if market_data.is_stale:
                continue
            if technical_analysis.technical_score < horizon_rule["min_score"]:
                continue
            horizon_score = self._candidate_horizon_score(technical_analysis, candidate_horizon)
            if horizon_score < horizon_rule["min_score"]:
                continue
            if strategy.action not in {"BUY", "HOLD"} or strategy.reasoning == "data-limited":
                continue
            action_update = {}
            if strategy.action == "HOLD":
                action_update = {
                    "action": "WATCH",
                    "reasoning": (
                        "보유하지 않은 후보이므로 신규 매수 대기(WATCH)로 해석합니다. "
                        f"{strategy.reasoning}"
                    ),
                }
            strategy = strategy.model_copy(
                update={
                    **action_update,
                    "reasoning": (
                        f"보유 외 추가 매수 후보({horizon_rule['label']} 목표): "
                        f"{action_update.get('reasoning', strategy.reasoning)}"
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

    def _build_analysis_rows(
        self,
        assets: list[dict[str, Any]],
        stale_data_business_days: int,
        risk_profile: str,
    ) -> list[dict[str, Any]]:
        if not assets:
            return []
        rows = []
        with ThreadPoolExecutor(max_workers=min(5, len(assets))) as executor:
            futures = {
                executor.submit(
                    self._build_single_analysis_row,
                    asset,
                    stale_data_business_days,
                    risk_profile,
                ): asset
                for asset in assets
            }
            for future in as_completed(futures):
                try:
                    rows.append(future.result())
                except Exception as exc:
                    asset = futures[future]
                    log_external_failure(
                        "market_data",
                        exc,
                        {"operation": "build_analysis_row", "ticker": asset.get("ticker")},
                    )
        order = {id(asset): index for index, asset in enumerate(assets)}
        return sorted(rows, key=lambda row: order.get(id(row["asset"]), 0))

    def _build_single_analysis_row(
        self,
        asset: dict[str, Any],
        stale_data_business_days: int,
        risk_profile: str,
    ) -> dict[str, Any]:
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
        return {
            "asset": asset,
            "market_data": market_data,
            "technical_analysis": technical_analysis,
            "strategy": strategy,
        }

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

    def _build_news_context(
        self,
        report_type: str,
        assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            return self.news_service.fetch_report_context(report_type, assets)
        except Exception as exc:
            log_external_failure("gdelt", exc, {"operation": "build_news_context"})
            return {
                "provider": "gdelt_doc_2_0",
                "status": "unavailable",
                "articles": [],
                "queries": [],
            }

    def _save_report(
        self,
        content: ReportContent,
        assets: list[dict[str, Any]],
        candidate_horizon: str,
        portfolio_summary: dict[str, Any],
        frontend_timezone: str,
    ) -> dict[str, Any]:
        report = self.repository.create_report(
            {
                "report_type": content.report_type,
                "title": f"{self._report_type_label(content.report_type)} 시장 리포트",
                "summary": content.market_summary.summary,
                "content": content.model_dump(mode="json"),
            }
        )
        assets_by_ticker = {asset["ticker"]: asset for asset in assets}
        existing_logs = self.repository.list_performance_logs(limit=500)
        existing_strategies = {row["id"]: row for row in self.repository.list_strategies()}
        existing_cycles = self.repository.list_recommendation_cycles(limit=500)
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
            if self._should_start_performance_log(strategy, existing_logs, existing_strategies):
                self.repository.create_performance_log(
                    {
                        "strategy_id": strategy_row["id"],
                        "ticker": strategy.ticker,
                        "action": strategy.action,
                        "price_at_recommendation": strategy.current_price,
                    }
                )
            self._sync_recommendation_cycle(
                strategy=strategy,
                strategy_row=strategy_row,
                report=report,
                horizon=candidate_horizon,
                existing_cycles=existing_cycles,
            )
        self._save_portfolio_snapshot(
            report=report,
            report_type=content.report_type,
            portfolio_summary=portfolio_summary,
            frontend_timezone=frontend_timezone,
        )
        return report

    def _save_portfolio_snapshot(
        self,
        report: dict[str, Any],
        report_type: str,
        portfolio_summary: dict[str, Any],
        frontend_timezone: str,
    ) -> None:
        try:
            tz = ZoneInfo(frontend_timezone)
        except Exception:
            tz = timezone.utc
        try:
            self.repository.create_portfolio_snapshot(
                {
                    "report_id": report.get("id"),
                    "report_type": report_type,
                    "snapshot_date": datetime.now(tz).date().isoformat(),
                    "total_market_value": portfolio_summary.get("total_market_value") or 0,
                    "total_cost": portfolio_summary.get("total_cost") or 0,
                    "total_profit_loss": portfolio_summary.get("total_profit_loss") or 0,
                    "total_return_rate": portfolio_summary.get("total_return_rate") or 0,
                    "daily_profit_loss": portfolio_summary.get("daily_profit_loss") or 0,
                    "daily_return_rate": portfolio_summary.get("daily_return_rate") or 0,
                    "domestic_value": portfolio_summary.get("domestic_value") or 0,
                    "global_value": portfolio_summary.get("global_value") or 0,
                    "cash_value": portfolio_summary.get("cash_value") or 0,
                    "usd_krw_rate": portfolio_summary.get("usd_krw_rate") or 1400,
                    "asset_allocation": portfolio_summary.get("asset_allocation") or [],
                    "asset_returns": portfolio_summary.get("asset_returns") or [],
                }
            )
        except Exception as exc:
            log_external_failure(
                "portfolio_snapshots",
                exc,
                {"operation": "create_portfolio_snapshot", "report_id": report.get("id")},
            )

    def _sync_recommendation_cycle(
        self,
        strategy: AssetStrategy,
        strategy_row: dict[str, Any],
        report: dict[str, Any],
        horizon: str,
        existing_cycles: list[dict[str, Any]],
    ) -> None:
        if strategy.current_price is None or strategy.reasoning == "data-limited":
            return
        active_cycles = [
            row
            for row in existing_cycles
            if row.get("ticker") == strategy.ticker
            and row.get("horizon") == horizon
            and row.get("status") == "active"
        ]
        reusable_cycle = next(
            (
                row
                for row in active_cycles
                if row.get("action") == strategy.action
                and not self._material_price_change(row, strategy)
            ),
            None,
        )
        now = datetime.now(timezone.utc).isoformat()
        if reusable_cycle:
            updated = self.repository.update_recommendation_cycle(
                reusable_cycle["id"],
                {
                    "strategy_id": strategy_row["id"],
                    "report_id": report["id"],
                    "target_price": strategy.target_price,
                    "stop_loss": strategy.stop_loss,
                    "metadata": {
                        **(reusable_cycle.get("metadata") or {}),
                        "last_seen_at": now,
                        "latest_confidence": strategy.confidence,
                    },
                },
            )
            if updated:
                existing_cycles[:] = [
                    updated if row.get("id") == updated.get("id") else row
                    for row in existing_cycles
                ]
            return

        for row in active_cycles:
            closed = self.repository.update_recommendation_cycle(
                row["id"],
                {
                    "status": "superseded",
                    "closed_at": now,
                    "metadata": {
                        **(row.get("metadata") or {}),
                        "superseded_by_strategy_id": strategy_row["id"],
                    },
                },
            )
            if closed:
                existing_cycles[:] = [
                    closed if item.get("id") == closed.get("id") else item
                    for item in existing_cycles
                ]

        created = self.repository.create_recommendation_cycle(
            {
                "strategy_id": strategy_row["id"],
                "report_id": report["id"],
                "report_type": report["report_type"],
                "ticker": strategy.ticker,
                "name": strategy.name,
                "action": strategy.action,
                "horizon": horizon,
                "status": "active",
                "reference_price": strategy.current_price,
                "target_price": strategy.target_price,
                "stop_loss": strategy.stop_loss,
                "metadata": {
                    "confidence": strategy.confidence,
                    "buy_range_low": strategy.buy_range_low,
                    "buy_range_high": strategy.buy_range_high,
                    "sell_range_low": strategy.sell_range_low,
                    "sell_range_high": strategy.sell_range_high,
                    "reasoning": strategy.reasoning,
                },
            }
        )
        existing_cycles.append(created)

    def _material_price_change(self, cycle: dict[str, Any], strategy: AssetStrategy) -> bool:
        return self._price_changed(cycle.get("target_price"), strategy.target_price) or (
            self._price_changed(cycle.get("stop_loss"), strategy.stop_loss)
        )

    def _price_changed(self, old_value: Any, new_value: Any) -> bool:
        if old_value is None and new_value is None:
            return False
        if old_value is None or new_value is None:
            return True
        old_float = float(old_value)
        new_float = float(new_value)
        if old_float == 0:
            return new_float != 0
        return abs(new_float - old_float) / abs(old_float) >= RECOMMENDATION_PRICE_CHANGE_THRESHOLD

    def _should_start_performance_log(
        self,
        strategy: AssetStrategy,
        existing_logs: list[dict[str, Any]],
        existing_strategies: dict[str, dict[str, Any]],
    ) -> bool:
        if strategy.current_price is None or strategy.reasoning == "data-limited":
            return False
        for log_row in existing_logs:
            if log_row.get("ticker") != strategy.ticker or log_row.get("action") != strategy.action:
                continue
            existing_strategy = existing_strategies.get(log_row.get("strategy_id"), {})
            created_at = parse_iso_datetime(
                existing_strategy.get("created_at") or log_row.get("created_at")
            )
            if created_at is None:
                return False
            age_days = (datetime.now(timezone.utc) - created_at.astimezone(timezone.utc)).days
            if age_days <= 1:
                return False
            if log_row.get("price_after_20d") is not None:
                continue
            if age_days <= 35:
                return False
        return True

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

    def _append_news_context_note(
        self,
        content: ReportContent,
        news_context: dict[str, Any],
    ) -> ReportContent:
        articles = news_context.get("articles") or []
        status = news_context.get("status")
        macro_factors = list(content.market_summary.macro_factors)
        key_risks = list(content.key_risks)
        if status == "ok" and articles:
            note = f"최근 뉴스/동향 컨텍스트(GDELT) {len(articles)}건을 분석 입력에 반영했습니다."
            if note not in macro_factors:
                macro_factors.append(note)
        elif status in {"empty", "unavailable"}:
            note = "최근 뉴스/동향 컨텍스트가 제한적이어서 기술·시장 데이터 비중을 높였습니다."
            if note not in key_risks:
                key_risks.append(note)
        return content.model_copy(
            update={
                "market_summary": content.market_summary.model_copy(
                    update={"macro_factors": macro_factors}
                ),
                "key_risks": key_risks,
            }
        )

    def _assets_for_report(
        self, assets: list[dict[str, Any]], report_type: str
    ) -> list[dict[str, Any]]:
        markets = {"KR"} if report_type == "domestic" else {"US", "ETF"}
        return [asset for asset in assets if asset.get("market") in markets]

    def _candidate_assets(self, report_type: str) -> list[dict[str, Any]]:
        market_filter = {"KR"} if report_type == "domestic" else {"US", "ETF"}
        try:
            candidate_rows = self.repository.list_candidate_assets()
        except Exception as exc:
            log_external_failure(
                "candidate_assets",
                exc,
                {"operation": "list_candidate_assets_for_report"},
            )
            candidate_rows = []
        configured_candidates = [
            row
            for row in candidate_rows
            if row.get("is_active", True) and row.get("market") in market_filter
        ]
        if configured_candidates:
            return [
                {
                    "id": None,
                    "market": candidate["market"],
                    "ticker": candidate["ticker"],
                    "name": candidate["name"],
                    "currency": candidate.get("currency") or "KRW",
                    "quantity": 0,
                    "avg_price": 0,
                    "memo": candidate.get("memo") or "보유 외 추천 후보",
                }
                for candidate in configured_candidates
            ]
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
            "output. Use decision-support language only. Do not add a news_factors field. Include "
            "action, confidence, ranges, target, stop-loss, reasoning, risk, and invalidation "
            "condition for each non-stale strategy. Write user-facing text fields in Korean, "
            "including market_summary.summary, macro_factors, key_risks, opportunities, "
            "reasoning, risk, invalidation_condition, and allocation_comment. Keep schema keys, "
            "ticker symbols, and action enum values in English exactly as required. Do not write "
            "English sentences in user-facing fields unless the field value is a ticker, provider "
            "name, schema key, or action enum. context.candidate_tickers contains non-owned "
            "screened buy candidates. Include them in asset_strategies when they are present, and "
            "make their reasoning clearly say they are 보유 외 추가 매수 후보. "
            "For non-owned candidates, do not use HOLD; use BUY for active entry ideas and WATCH "
            "for waitlisted ideas. "
            "context.candidate_horizon is the target holding/profit-taking horizon for those "
            "candidate ideas. context.news_context contains recent GDELT news/trend headlines. "
            "Use it only when relevant inside allowed fields such as macro_factors, key_risks, "
            "opportunities, reasoning, and risk. Do not cite unsupported details or create a "
            "separate news section."
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

    def _refresh_usd_krw_rate(self, app_settings: Any) -> Any:
        fetch_rate = getattr(self.market_data_service, "fetch_usd_krw_rate", None)
        if fetch_rate is None:
            return app_settings
        try:
            refreshed_rate = fetch_rate(app_settings.usd_krw_rate)
        except Exception as exc:
            log_external_failure("yfinance", exc, {"operation": "fetch_usd_krw_rate"})
            return app_settings
        if refreshed_rate is None or refreshed_rate <= 0:
            return app_settings
        if abs(float(refreshed_rate) - float(app_settings.usd_krw_rate)) < 0.01:
            return app_settings
        try:
            saved = self.repository.upsert_settings({"usd_krw_rate": float(refreshed_rate)})
            return resolve_application_settings(saved, get_env_application_defaults())
        except Exception as exc:
            log_external_failure("settings", exc, {"operation": "refresh_usd_krw_rate"})
            return app_settings

    def _infer_market(self, ticker: str) -> str:
        clean = ticker.replace(".KS", "").replace(".KQ", "")
        if len(clean) == 6 and clean.isalnum():
            return "KR"
        return "US"

    def _normalize_ticker(self, ticker: str) -> str:
        return str(ticker).upper().replace(".KS", "").replace(".KQ", "").strip()
