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
from app.services.portfolio_risk_service import PortfolioRiskService
from app.services.recommendation_stats_service import ConfidenceCalibrator
from app.services.report import candidate_screener
from app.services.report.advisory_context import build_advisory_context
from app.services.report.fact_enforcer import enforce_report_facts, forbidden_narrative_paths
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
from app.utils.assets import held_assets
from app.utils.labels import action_label, report_type_label, trend_label
from app.utils.logging import log_external_failure, log_structured_event
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

    def generate_report(
        self,
        report_type: str,
        generation_source: str = "manual",
    ) -> dict[str, Any]:
        if generation_source not in {"scheduled", "manual"}:
            raise ValueError("generation_source must be scheduled or manual")
        with self._timed_step("settings"):
            app_settings = resolve_application_settings(
                self.repository.get_settings(),
                get_env_application_defaults(),
            )
            app_settings = self._refresh_usd_krw_rate(app_settings)
            all_assets = held_assets(self.repository.list_assets())
            assets = self._assets_for_report(all_assets, report_type)
        with self._timed_step("sector_backfill"):
            self._backfill_sectors(assets)
        with self._timed_step("portfolio"):
            portfolio_summary = PortfolioService(
                self.repository,
                self.market_data_service,
            ).get_summary()
        with self._timed_step("asset_events"):
            asset_events = self._build_asset_events(all_assets)
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
        analyzed_asset_keys = {
            (
                str(row["asset"].get("market") or "").upper(),
                normalize_ticker(row["asset"].get("ticker", "")),
            )
            for row in analysis_rows
        }
        portfolio_risk_assets = [
            asset
            for asset in all_assets
            if asset.get("market") != "CASH"
            and (
                str(asset.get("market") or "").upper(),
                normalize_ticker(asset.get("ticker", "")),
            )
            not in analyzed_asset_keys
        ]
        with self._timed_step("portfolio_risk_context"):
            portfolio_risk_rows = self._build_analysis_rows(
                portfolio_risk_assets,
                app_settings.stale_data_business_days,
                app_settings.risk_profile,
            )
        portfolio_risk_analysis_rows = analysis_rows + portfolio_risk_rows
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
        with self._timed_step("advisory_context"):
            advisory_context = build_advisory_context(self.repository)
        generated_at = self._now(app_settings.frontend_timezone)

        with self._timed_step("ai_report"):
            content, ai_generation = self._generate_ai_content(
                report_type=report_type,
                app_settings=app_settings.model_dump(),
                portfolio_summary=portfolio_summary.model_dump(),
                analysis_rows=analysis_rows,
                index_rows=index_rows,
                technical_strategies=technical_strategies,
                stale_tickers=stale_tickers,
                news_context=news_context,
                asset_events=asset_events,
                advisory_context=advisory_context,
                owned_tickers=[normalize_ticker(asset.get("ticker", "")) for asset in all_assets],
                generated_at=generated_at,
            )
        if content is None:
            log_structured_event(
                "openai",
                "technical_fallback",
                {
                    "report_type": report_type,
                    "fallback_reason": ai_generation["fallback_reason"],
                    "attempt_count": ai_generation["attempt_count"],
                },
            )
            content = self._technical_only_report(
                report_type,
                portfolio_summary.model_dump(),
                index_rows,
                [row["strategy"] for row in analysis_rows],
                stale_tickers,
                app_settings.frontend_timezone,
                news_context,
                generated_at=generated_at,
            )
        else:
            content, fact_corrections = enforce_report_facts(
                content,
                analysis_rows,
                self._report_portfolio_summary(portfolio_summary.model_dump()).model_dump(),
                index_rows,
                report_type,
                generated_at,
            )
            ai_generation["fact_corrections"] = fact_corrections
            ai_generation["fact_correction_count"] = len(fact_corrections)
            if fact_corrections:
                log_structured_event(
                    "openai",
                    "backend_facts_restored",
                    {
                        "report_type": report_type,
                        "correction_count": len(fact_corrections),
                        "corrections": fact_corrections,
                    },
                )
            narrative_violations = forbidden_narrative_paths(content)
            if narrative_violations:
                ai_generation.update(
                    {
                        "mode": "technical_only",
                        "outcome": "fallback",
                        "fallback_reason": "forbidden_narrative",
                        "validation_paths": narrative_violations,
                    }
                )
                log_structured_event(
                    "openai",
                    "technical_fallback",
                    {
                        "report_type": report_type,
                        "fallback_reason": "forbidden_narrative",
                        "validation_paths": narrative_violations,
                    },
                )
                content = self._technical_only_report(
                    report_type,
                    portfolio_summary.model_dump(),
                    index_rows,
                    [row["strategy"] for row in analysis_rows],
                    stale_tickers,
                    app_settings.frontend_timezone,
                    news_context,
                    generated_at=generated_at,
                )
            else:
                log_structured_event(
                    "openai",
                    "ai_narrative_used",
                    {
                        "report_type": report_type,
                        "attempt_count": ai_generation["attempt_count"],
                        "fact_correction_count": len(fact_corrections),
                    },
                )
        content = self._append_news_context_note(content, news_context)
        content = self._append_asset_event_notes(content, asset_events)
        with self._timed_step("confidence_calibration"):
            content = self._apply_confidence_calibration(
                content,
                app_settings.candidate_horizon,
                news_context,
                analysis_rows,
            )
        if ai_generation["mode"] == "technical_only":
            content = self._cap_technical_only_confidence(content)
        content, position_sizing_snapshot = self._apply_position_sizing(
            content,
            portfolio_summary.model_dump(),
            app_settings,
            owned_tickers={normalize_ticker(asset.get("ticker", "")) for asset in all_assets},
            analysis_rows=portfolio_risk_analysis_rows,
        )

        report_inputs = self._build_report_inputs(
            analysis_rows,
            portfolio_risk_analysis_rows,
            news_context,
            advisory_context,
            asset_events,
            app_settings,
            content,
            ai_generation,
            position_sizing_snapshot,
        )
        with self._timed_step("save_report"):
            saved = self.persistence.save_report(
                content,
                assets,
                app_settings.candidate_horizon,
                portfolio_summary.model_dump(mode="json"),
                app_settings.frontend_timezone,
                report_inputs=report_inputs,
            )
        self._save_signal_model_report_link(saved, report_inputs, generation_source)
        with self._timed_step("performance_backfill"):
            self.backfill_performance_logs()
        with self._timed_step("recommendation_backfill"):
            self.backfill_recommendation_cycles()
        saved["content"] = content.model_dump(mode="json")
        return saved

    def _save_signal_model_report_link(
        self,
        report: dict[str, Any],
        report_inputs: dict[str, Any],
        generation_source: str,
    ) -> None:
        try:
            versions = {
                str(row.get("id")): row
                for row in self.repository.list_signal_model_versions()
                if row.get("id") is not None
            }
            active_champion_assignment = max(
                (
                    row
                    for row in self.repository.list_signal_model_assignments()
                    if row.get("role") == "champion" and row.get("ended_at") is None
                ),
                key=lambda row: str(row.get("effective_at") or row.get("created_at") or ""),
                default=None,
            )
            champion_version_id = (
                str(active_champion_assignment.get("model_version_id"))
                if active_champion_assignment is not None
                else None
            )
            if champion_version_id not in versions:
                return
            self.repository.create_signal_model_report_link(
                {
                    "report_id": report["id"],
                    "generation_source": generation_source,
                    "is_official_sample": generation_source == "scheduled",
                    "champion_assignment_id": str(active_champion_assignment["id"]),
                    "champion_version_id": champion_version_id,
                    "report_inputs_snapshot": report_inputs,
                    "evaluation_id": None,
                }
            )
        except Exception as exc:
            log_external_failure(
                "signal_model_report_links",
                exc,
                {
                    "operation": "create_report_link",
                    "report_id": report.get("id"),
                    "generation_source": generation_source,
                },
            )

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
        asset_events: dict[str, Any],
        advisory_context: dict[str, Any],
        owned_tickers: list[str],
        generated_at: str,
    ) -> tuple[ReportContent | None, dict[str, Any]]:
        diagnostics = {
            "mode": "technical_only",
            "provider": app_settings.get("ai_provider"),
            "model": app_settings.get("ai_model"),
            "prompt_version": PROMPT_VERSION,
            "attempt_count": 0,
            "outcome": "fallback",
            "fallback_reason": None,
            "fact_correction_count": 0,
            "fact_corrections": [],
        }
        try:
            provider = self.ai_provider or self._build_ai_provider(app_settings)
        except Exception as exc:
            log_external_failure("openai", exc, {"operation": "build_ai_provider"})
            diagnostics["fallback_reason"] = "provider_configuration_error"
            return None, diagnostics
        prompt = build_prompt(report_type)
        context = build_context(
            report_type=report_type,
            app_settings=app_settings,
            portfolio_summary=portfolio_summary,
            analysis_rows=analysis_rows,
            index_rows=index_rows,
            technical_strategies=technical_strategies,
            owned_tickers=owned_tickers,
            stale_tickers=stale_tickers,
            news_context=news_context,
            asset_events=asset_events,
            advisory_context=advisory_context,
            generated_at=generated_at,
        )

        validation_error: ValidationError | None = None
        for attempt in range(2):
            diagnostics["attempt_count"] = attempt + 1
            try:
                response = provider.generate_report(prompt, context)
                content = ReportContent.model_validate(response)
                diagnostics.update(
                    {
                        "mode": "ai_narrative",
                        "outcome": "success",
                        "fallback_reason": None,
                    }
                )
                return content, diagnostics
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
                diagnostics["fallback_reason"] = "provider_error"
                return None, diagnostics

        if validation_error is not None:
            log_external_failure(
                "openai",
                validation_error,
                {"operation": "validation_failed_after_retry"},
            )
        diagnostics["fallback_reason"] = "validation_failed"
        return None, diagnostics

    def _technical_only_report(
        self,
        report_type: str,
        portfolio_summary: dict[str, Any],
        index_rows: dict[str, TechnicalAnalysisResult],
        strategies: list[AssetStrategy],
        stale_tickers: list[str],
        frontend_timezone: str,
        news_context: dict[str, Any] | None = None,
        generated_at: str | None = None,
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
            generated_at=generated_at or self._now(frontend_timezone),
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
        analysis_rows: list[dict[str, Any]],
    ) -> ReportContent:
        """실측 승률 기반 신뢰도 보정과 산출 근거를 전략에 채운다 (Phase 4-2).

        표본이 부족한 밴드는 신뢰도를 바꾸지 않고 근거(calibrated=False)만 기록한다.
        실패해도 리포트 생성을 막지 않는다.
        """
        try:
            calibrator = ConfidenceCalibrator.from_repository(self.repository)
            news_articles = news_context.get("articles") or []
            backend_inputs = {
                normalize_ticker(row["asset"].get("ticker", "")): row for row in analysis_rows
            }
            calibrated_strategies = []
            for strategy in content.asset_strategies:
                if strategy.reasoning == "data-limited":
                    calibrated_strategies.append(strategy)
                    continue
                source_row = backend_inputs.get(normalize_ticker(strategy.ticker))
                source_strategy = source_row.get("strategy") if source_row else None
                technical_analysis = source_row.get("technical_analysis") if source_row else None
                base_confidence = strategy.confidence
                if (
                    source_strategy is not None
                    and strategy.reasoning != "technical-only fallback (LLM unavailable)"
                ):
                    base_confidence = source_strategy.confidence
                technical_score = (
                    technical_analysis.technical_score if technical_analysis is not None else None
                )
                strategy_text = " ".join(
                    (strategy.reasoning, strategy.risk, strategy.invalidation_condition)
                )
                news_used = any(
                    self._text_uses_news_evidence(strategy_text, article)
                    for article in news_articles
                )
                result = calibrator.calibrate(
                    action=strategy.action,
                    horizon=horizon,
                    base_confidence=base_confidence,
                    news_context_used=news_used,
                    technical_score=technical_score,
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

    def _apply_position_sizing(
        self,
        content: ReportContent,
        portfolio_summary: dict[str, Any],
        app_settings: Any,
        owned_tickers: set[str],
        analysis_rows: list[dict[str, Any]],
    ) -> tuple[ReportContent, dict[str, Any]]:
        """신규 매수 후보에 고정 리스크(fixed-fractional) 기반 제안 투입 한도를 채운다 (Phase 5-3).

        suggested = min(가용 현금 × 성향별 비율, 1회 리스크 한도 ÷ 손절까지 거리 비율).
        금액 범위만 안내하며 주문 수량/티켓은 만들지 않는다 (자동매매 금지 원칙 유지).
        """
        try:
            sizes, snapshot = PortfolioRiskService().calculate_position_sizing(
                strategies=content.asset_strategies,
                analysis_rows=analysis_rows,
                portfolio_summary=portfolio_summary,
                app_settings=app_settings,
                owned_tickers=owned_tickers,
            )
            updated_strategies = [
                (
                    strategy.model_copy(
                        update={"position_sizing": sizes[normalize_ticker(strategy.ticker)]}
                    )
                    if normalize_ticker(strategy.ticker) in sizes
                    else strategy
                )
                for strategy in content.asset_strategies
            ]
            return content.model_copy(update={"asset_strategies": updated_strategies}), snapshot
        except Exception as exc:
            log_external_failure("position_sizing", exc, {"operation": "apply_position_sizing"})
            return content, {"status": "unavailable"}

    def _build_report_inputs(
        self,
        analysis_rows: list[dict[str, Any]],
        portfolio_risk_analysis_rows: list[dict[str, Any]],
        news_context: dict[str, Any],
        advisory_context: dict[str, Any],
        asset_events: dict[str, Any],
        app_settings: Any,
        content: ReportContent,
        ai_generation: dict[str, Any],
        position_sizing_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """리포트 입력 스냅샷(데이터 품질 배지/사후 검증용, Phase 4-4)."""
        tickers: dict[str, Any] = {}
        position_sizing_by_ticker = {
            strategy.ticker: strategy.position_sizing for strategy in content.asset_strategies
        }
        for row in analysis_rows:
            market_data = row["market_data"]
            strategy = row["strategy"]
            last_trading_date = market_data.last_trading_date
            tickers[row["asset"]["ticker"]] = {
                "provider": market_data.provider,
                "last_trading_date": (last_trading_date.isoformat() if last_trading_date else None),
                "is_stale": market_data.is_stale,
                "data_quality_note": market_data.data_quality_note,
                "technical_score": row["technical_analysis"].technical_score,
                "current_price": strategy.current_price,
                "action": strategy.action,
                "base_confidence": strategy.confidence,
                "buy_range_low": strategy.buy_range_low,
                "buy_range_high": strategy.buy_range_high,
                "sell_range_low": strategy.sell_range_low,
                "sell_range_high": strategy.sell_range_high,
                "target_price": strategy.target_price,
                "stop_loss": strategy.stop_loss,
                "is_candidate": row["asset"].get("id") is None,
                "sector": row["asset"].get("sector"),
                "position_sizing": position_sizing_by_ticker.get(row["asset"]["ticker"]),
            }
        portfolio_risk_market_inputs: dict[str, Any] = {}
        for row in portfolio_risk_analysis_rows:
            asset = row["asset"]
            market_data = row["market_data"]
            last_trading_date = market_data.last_trading_date
            key = f"{str(asset.get('market') or '').upper()}:{asset.get('ticker')}"
            portfolio_risk_market_inputs[key] = {
                "market": asset.get("market"),
                "ticker": asset.get("ticker"),
                "currency": asset.get("currency"),
                "provider": market_data.provider,
                "last_trading_date": (last_trading_date.isoformat() if last_trading_date else None),
                "is_stale": market_data.is_stale,
                "data_quality_note": market_data.data_quality_note,
                "return_observations": max(len(market_data.dataframe.index) - 1, 0),
                "is_candidate": asset.get("id") is None,
            }
        portfolio_risk_snapshot = {
            **position_sizing_snapshot,
            "market_inputs": portfolio_risk_market_inputs,
        }
        return {
            "prompt_version": PROMPT_VERSION,
            "ai_generation": ai_generation,
            "tickers": tickers,
            "portfolio_risk": portfolio_risk_snapshot,
            "news_context": self._news_input_snapshot(news_context, content),
            "advisory_context": advisory_context,
            "asset_events": asset_events,
            "settings": {
                "risk_profile": app_settings.risk_profile,
                "candidate_horizon": app_settings.candidate_horizon,
                "stale_data_business_days": app_settings.stale_data_business_days,
                "position_sizing": position_sizing_snapshot,
            },
        }

    def _cap_technical_only_confidence(self, content: ReportContent) -> ReportContent:
        return content.model_copy(
            update={
                "asset_strategies": [
                    strategy.model_copy(update={"confidence": min(strategy.confidence, 60)})
                    for strategy in content.asset_strategies
                ]
            }
        )

    def _build_asset_events(self, assets: list[dict[str, Any]]) -> dict[str, Any]:
        fetch_events = getattr(self.market_data_service, "fetch_asset_events", None)
        if fetch_events is None:
            return {
                "provider": "yfinance",
                "status": "unavailable",
                "events": [],
                "window_days": 60,
            }
        try:
            return fetch_events(assets, days=60)
        except Exception as exc:
            log_external_failure("yfinance", exc, {"operation": "build_asset_events"})
            return {
                "provider": "yfinance",
                "status": "unavailable",
                "events": [],
                "window_days": 60,
            }

    def _build_news_context(
        self,
        report_type: str,
        assets: list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            context = self.news_service.fetch_report_context(report_type, assets)
            context["articles"] = [
                {
                    **article,
                    "evidence_id": article.get("evidence_id") or f"N{index}",
                }
                for index, article in enumerate(context.get("articles") or [], start=1)
            ]
            return context
        except Exception as exc:
            log_external_failure("gdelt", exc, {"operation": "build_news_context"})
            return {
                "provider": "gdelt_doc_2_0",
                "status": "unavailable",
                "articles": [],
                "queries": [],
                "query_details": [],
                "failure_count": 1,
                "failure_reasons": ["pipeline_error"],
            }

    def _news_input_snapshot(
        self,
        news_context: dict[str, Any],
        content: ReportContent,
    ) -> dict[str, Any]:
        articles = news_context.get("articles") or []
        evidence_usage = self._news_evidence_usage(content, articles)
        used_evidence_ids = sorted({row["evidence_id"] for row in evidence_usage})
        query_details = news_context.get("query_details") or [
            {"query": query, "scope": "unknown"} for query in news_context.get("queries") or []
        ]
        return {
            "provider": news_context.get("provider"),
            "status": news_context.get("status"),
            "timespan": news_context.get("timespan"),
            "generated_at": news_context.get("generated_at"),
            "article_count": len(articles),
            "news_context_used": bool(used_evidence_ids),
            "news_contribution_score": 0.0,
            "news_contribution_mode": "not_modeled",
            "evidence_mode": "headline-only",
            "queries": query_details,
            "articles": [
                {
                    key: article.get(key)
                    for key in (
                        "query",
                        "evidence_id",
                        "query_scope",
                        "asset_ticker",
                        "asset_name",
                        "subject_kind",
                        "title",
                        "domain",
                        "url",
                        "source_country",
                        "language",
                        "seen_at",
                        "collected_at",
                        "evidence_level",
                    )
                }
                for article in articles
            ],
            "failure_count": news_context.get("failure_count", 0),
            "failure_reasons": news_context.get("failure_reasons", []),
            "failures": news_context.get("failures", []),
            "excluded_articles": news_context.get("excluded_articles", []),
            "used_evidence_ids": used_evidence_ids,
            "evidence_usage": evidence_usage,
        }

    def _news_evidence_usage(
        self,
        content: ReportContent,
        articles: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        fields: list[tuple[str, str]] = [
            ("market_summary.summary", content.market_summary.summary),
            *[
                (f"market_summary.macro_factors[{index}]", value)
                for index, value in enumerate(content.market_summary.macro_factors)
            ],
            *[(f"key_risks[{index}]", value) for index, value in enumerate(content.key_risks)],
            *[
                (f"opportunities[{index}]", value)
                for index, value in enumerate(content.opportunities)
            ],
        ]
        for index, strategy in enumerate(content.asset_strategies):
            fields.extend(
                [
                    (f"asset_strategies[{index}].reasoning", strategy.reasoning),
                    (f"asset_strategies[{index}].risk", strategy.risk),
                    (
                        f"asset_strategies[{index}].invalidation_condition",
                        strategy.invalidation_condition,
                    ),
                ]
            )
        return [
            {"evidence_id": article["evidence_id"], "output_path": path}
            for path, value in fields
            for article in articles
            if article.get("evidence_id") and self._text_uses_news_evidence(value, article)
        ]

    def _text_uses_news_evidence(self, value: str, article: dict[str, Any]) -> bool:
        evidence_id = str(article.get("evidence_id") or "")
        domain = str(article.get("domain") or "")
        url = str(article.get("url") or "")
        seen_date = str(article.get("seen_at") or "")[:10]
        return bool(
            evidence_id
            and domain
            and url
            and seen_date
            and f"[{evidence_id}" in value
            and domain in value
            and url in value
            and seen_date in value
        )

    def _enforce_stale_rules(
        self,
        content: ReportContent,
        analysis_rows: list[dict[str, Any]],
        stale_tickers: list[str],
    ) -> ReportContent:
        by_ticker = {strategy.ticker: strategy for strategy in content.asset_strategies}
        for row in analysis_rows:
            if (
                row["asset"]["ticker"] in stale_tickers
                or row["strategy"].reasoning == "data-limited"
                or row["asset"]["ticker"] not in by_ticker
            ):
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
        if status in {"ok", "partial"} and articles:
            note = f"최근 뉴스/동향 헤드라인 {len(articles)}건을 분석 입력으로 참고했습니다."
            if note not in macro_factors:
                macro_factors.append(note)
            if status == "partial":
                risk_note = "일부 뉴스 검색이 실패해 제공된 헤드라인만 제한적으로 사용했습니다."
                if risk_note not in key_risks:
                    key_risks.append(risk_note)
        elif status in {"empty", "unavailable", "partial"}:
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

    def _append_asset_event_notes(
        self,
        content: ReportContent,
        asset_events: dict[str, Any],
    ) -> ReportContent:
        events = asset_events.get("events") or []
        key_risks = list(content.key_risks)
        opportunities = list(content.opportunities)
        for event in events[:8]:
            date_text = str(event.get("date") or "")[:10]
            note = (
                f"{event.get('ticker')} {event.get('label')} 예정({date_text}): "
                "일정 전후 변동성과 발표 내용을 확인하세요."
            )
            target = key_risks if event.get("event_type") == "earnings" else opportunities
            if note not in target:
                target.append(note)
        return content.model_copy(
            update={
                "key_risks": key_risks,
                "opportunities": opportunities,
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
