"""리포트 생성 파이프라인 오케스트레이션.

데이터 수집 → 분석 → LLM 생성(또는 기술 전용 폴백) → 저장 → 성과 백필 순서만 담당하고,
세부 책임은 candidate_screener / prompt_builder / persistence / tracking 모듈에 위임한다.
"""

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
from app.services.recommendation_stats_service import ConfidenceCalibrator
from app.services.report import candidate_screener
from app.services.report.persistence import ReportPersistence
from app.services.report.prompt_builder import (
    DISCLAIMER,
    PROMPT_VERSION,
    build_context,
    build_prompt,
)
from app.services.report.tracking import PerformanceTracker
from app.services.report_job_service import ReportJobStore
from app.services.strategy_service import StrategyService
from app.services.technical_analysis_service import (
    TechnicalAnalysisResult,
    TechnicalAnalysisService,
)
from app.utils.labels import action_label, report_type_label, trend_label
from app.utils.logging import log_external_failure
from app.utils.tickers import infer_market, normalize_ticker


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
        self.persistence = ReportPersistence(repository)

    def generate_report(self, report_type: str) -> dict[str, Any]:
        with self._timed_step("settings"):
            app_settings = resolve_application_settings(
                self.repository.get_settings(),
                get_env_application_defaults(),
            )
            app_settings = self._refresh_usd_krw_rate(app_settings)
            all_assets = self.repository.list_assets()
            assets = self._assets_for_report(all_assets, report_type)
        with self._timed_step("sector_backfill"):
            self._backfill_sectors(assets)
        with self._timed_step("portfolio"):
            portfolio_summary = PortfolioService(
                self.repository,
                self.market_data_service,
            ).get_summary()
        with self._timed_step("owned_asset_analysis"):
            analysis_rows = self._build_analysis_rows(
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
        with self._timed_step("confidence_calibration"):
            content = self._apply_confidence_calibration(
                content, app_settings.candidate_horizon, news_context
            )

        with self._timed_step("save_report"):
            saved = self.persistence.save_report(
                content,
                assets,
                app_settings.candidate_horizon,
                portfolio_summary.model_dump(mode="json"),
                app_settings.frontend_timezone,
                report_inputs=self._build_report_inputs(analysis_rows, news_context, app_settings),
            )
        with self._timed_step("performance_backfill"):
            self.backfill_performance_logs()
        with self._timed_step("recommendation_backfill"):
            self.backfill_recommendation_cycles()
        saved["content"] = content.model_dump(mode="json")
        return saved

    def backfill_performance_logs(self) -> None:
        PerformanceTracker(self.repository, self.market_data_service).backfill_performance_logs()

    def backfill_recommendation_cycles(self) -> None:
        PerformanceTracker(
            self.repository, self.market_data_service
        ).backfill_recommendation_cycles()

    def _timed_step(self, step_name: str) -> Any:
        if self.report_job_store is None or not self.report_job_id:
            return nullcontext()
        return self.report_job_store.time_step(self.report_job_id, step_name)

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
        prompt = build_prompt(report_type)
        context = build_context(
            report_type=report_type,
            app_settings=app_settings,
            portfolio_summary=portfolio_summary,
            analysis_rows=analysis_rows,
            index_rows=index_rows,
            technical_strategies=technical_strategies,
            owned_tickers=[
                normalize_ticker(asset.get("ticker", "")) for asset in self.repository.list_assets()
            ],
            stale_tickers=stale_tickers,
            news_context=news_context,
            generated_at=self._now(app_settings["frontend_timezone"]),
        )

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
            f"{strategy.ticker}: 기술 점수 기준 {action_label(strategy.action)} 후보"
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

    def _build_candidate_analysis(
        self,
        report_type: str,
        all_assets: list[dict[str, Any]],
        stale_data_business_days: int,
        risk_profile: str,
        candidate_horizon: str,
    ) -> list[dict[str, Any]]:
        owned_tickers = {normalize_ticker(asset.get("ticker", "")) for asset in all_assets}
        candidate_assets = [
            asset
            for asset in candidate_screener.candidate_assets(self.repository, report_type)
            if normalize_ticker(asset["ticker"]) not in owned_tickers
        ]
        analysis_rows = self._build_analysis_rows(
            candidate_assets,
            stale_data_business_days,
            risk_profile,
        )
        return candidate_screener.screen_candidate_rows(
            analysis_rows,
            owned_tickers,
            candidate_horizon,
        )

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

    def _backfill_sectors(self, assets: list[dict[str, Any]]) -> None:
        """sector가 비어 있는 보유 자산에 yfinance 섹터 정보를 보충한다 (Phase 4-3)."""
        fetch_sector = getattr(self.market_data_service, "fetch_sector", None)
        if fetch_sector is None:
            return
        for asset in assets:
            if asset.get("sector") or asset.get("market") == "CASH" or not asset.get("id"):
                continue
            try:
                sector = fetch_sector(asset["market"], asset["ticker"])
            except Exception as exc:
                log_external_failure(
                    "yfinance",
                    exc,
                    {"operation": "backfill_sector", "ticker": asset.get("ticker")},
                )
                continue
            if not sector:
                continue
            try:
                self.repository.update_asset(asset["id"], {"sector": sector})
                asset["sector"] = sector
            except Exception as exc:
                log_external_failure(
                    "assets",
                    exc,
                    {"operation": "save_sector", "ticker": asset.get("ticker")},
                )

    def _apply_confidence_calibration(
        self,
        content: ReportContent,
        horizon: str,
        news_context: dict[str, Any],
    ) -> ReportContent:
        """실측 승률 기반 신뢰도 보정과 산출 근거를 전략에 채운다 (Phase 4-2).

        표본이 부족한 밴드는 신뢰도를 바꾸지 않고 근거(calibrated=False)만 기록한다.
        실패해도 리포트 생성을 막지 않는다.
        """
        try:
            calibrator = ConfidenceCalibrator.from_repository(self.repository)
            news_used = news_context.get("status") == "ok" and bool(news_context.get("articles"))
            calibrated_strategies = []
            for strategy in content.asset_strategies:
                if strategy.reasoning == "data-limited":
                    calibrated_strategies.append(strategy)
                    continue
                result = calibrator.calibrate(
                    action=strategy.action,
                    horizon=horizon,
                    base_confidence=strategy.confidence,
                    news_context_used=news_used,
                )
                calibrated_strategies.append(
                    strategy.model_copy(
                        update={
                            "confidence": result["confidence"],
                            "confidence_detail": result["detail"],
                        }
                    )
                )
            return content.model_copy(update={"asset_strategies": calibrated_strategies})
        except Exception as exc:
            log_external_failure(
                "recommendation_stats", exc, {"operation": "confidence_calibration"}
            )
            return content

    def _build_report_inputs(
        self,
        analysis_rows: list[dict[str, Any]],
        news_context: dict[str, Any],
        app_settings: Any,
    ) -> dict[str, Any]:
        """리포트 입력 스냅샷(데이터 품질 배지/사후 검증용, Phase 4-4)."""
        tickers: dict[str, Any] = {}
        for row in analysis_rows:
            market_data = row["market_data"]
            last_trading_date = market_data.last_trading_date
            tickers[row["asset"]["ticker"]] = {
                "provider": market_data.provider,
                "last_trading_date": (last_trading_date.isoformat() if last_trading_date else None),
                "is_stale": market_data.is_stale,
                "data_quality_note": market_data.data_quality_note,
                "technical_score": row["technical_analysis"].technical_score,
                "is_candidate": row["asset"].get("id") is None,
                "sector": row["asset"].get("sector"),
            }
        return {
            "prompt_version": PROMPT_VERSION,
            "tickers": tickers,
            "news_context": {
                "provider": news_context.get("provider"),
                "status": news_context.get("status"),
                "article_count": len(news_context.get("articles") or []),
            },
            "settings": {
                "risk_profile": app_settings.risk_profile,
                "candidate_horizon": app_settings.candidate_horizon,
                "stale_data_business_days": app_settings.stale_data_business_days,
            },
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

    def _build_ai_provider(self, app_settings: dict[str, Any]) -> AIProvider:
        if app_settings.get("ai_provider") != "openai":
            raise RuntimeError("unsupported AI provider for MVP")
        env = get_environment_settings()
        return OpenAIProvider(
            api_key=env.openai_api_key,
            model=app_settings["ai_model"],
        )

    def _index_summary(
        self,
        report_type: str,
        index_rows: dict[str, TechnicalAnalysisResult],
    ) -> str:
        if not index_rows:
            return f"{report_type_label(report_type)} 시장 기술 데이터가 제한적입니다."
        parts = [
            f"{name} 기술 점수 {result.technical_score} ({trend_label(result.trend_label)})"
            for name, result in index_rows.items()
        ]
        return f"{report_type_label(report_type)} 시장 기술 요약: " + "; ".join(parts)

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
        rounded_rate = round(float(refreshed_rate), 4)
        if abs(rounded_rate - float(app_settings.usd_krw_rate)) < 0.01:
            return app_settings
        try:
            saved = self.repository.upsert_settings({"usd_krw_rate": rounded_rate})
            return resolve_application_settings(saved, get_env_application_defaults())
        except Exception as exc:
            log_external_failure("settings", exc, {"operation": "refresh_usd_krw_rate"})
            return app_settings

    # 하위 호환: 기존 호출부/테스트가 사용하는 내부 헬퍼를 위임 형태로 유지한다.
    def _sync_recommendation_cycle(
        self,
        strategy: AssetStrategy,
        strategy_row: dict[str, Any],
        report: dict[str, Any],
        horizon: str,
        existing_cycles: list[dict[str, Any]],
    ) -> None:
        self.persistence.sync_recommendation_cycle(
            strategy=strategy,
            strategy_row=strategy_row,
            report=report,
            horizon=horizon,
            existing_cycles=existing_cycles,
        )

    def _infer_market(self, ticker: str) -> str:
        return infer_market(ticker)

    def _normalize_ticker(self, ticker: str) -> str:
        return normalize_ticker(ticker)
