import pandas as pd
import pytest
from types import SimpleNamespace

from app.db.supabase_client import InMemoryRepository
from app.models.settings import Settings
from app.services.backtest_service import RuleBacktestService, action_for_score
from app.services.market_data_service import MarketDataResult
from app.services.strategy_service import StrategyService


class FakeMarketData:
    def __init__(self, size=180):
        self.size = size

    def fetch_price_history(self, *_args, **_kwargs):
        index = pd.date_range("2023-01-02", periods=self.size, freq="B")
        values = pd.Series(range(100, 100 + self.size), index=index, dtype=float)
        frame = pd.DataFrame(
            {
                "open": values,
                "high": values + 1,
                "low": values - 1,
                "close": values,
                "volume": values * 10,
            },
            index=index,
        )
        return MarketDataResult(frame, None, False, "mock", "ok", float(values.iloc[-1]))


@pytest.mark.parametrize("risk_profile", ["conservative", "balanced", "aggressive"])
@pytest.mark.parametrize("score", [34, 35, 49, 50, 64, 65, 79, 80])
def test_action_for_score_matches_operational_mapping(risk_profile, score):
    assert action_for_score(score, risk_profile) == StrategyService.action_for_score(
        score, risk_profile
    )


def test_rule_backtest_returns_reproducible_simulation_groups():
    repository = InMemoryRepository()
    repository.upsert_candidate_universe(
        {
            "report_type": "global",
            "market": "US",
            "ticker": "AAPL",
            "name": "Apple",
            "currency": "USD",
            "source": "test",
        }
    )

    result = RuleBacktestService(repository, FakeMarketData()).run("global")

    assert result["tickers_tested"] == ["AAPL"]
    assert result["sample_count"] > 0
    assert result["groups"]
    assert all(group["avg_forward_return"] > 0 for group in result["groups"])
    assert all(
        group["avg_net_return_pct"] <= group["avg_gross_return_pct"] for group in result["groups"]
    )
    assert (
        result["metrics"]["gross"]["cumulative_return_pct"]
        >= result["metrics"]["net"]["cumulative_return_pct"]
    )
    assert result["costs"]["total_cost_pct"] > 0
    assert {row["name"] for row in result["baselines"]} == {
        "buy_and_hold",
        "sma_trend",
        "simple_momentum",
    }
    assert result["strategy_version"]
    assert result["settings_snapshot"]["risk_profile"] == "balanced"
    assert result["settings_snapshot"]["usd_krw_rate"] == 1400
    assert result["input_snapshot"]["universe"][0]["ticker"] == "AAPL"
    assert result["input_snapshot"]["data_sources"][0]["provider"] == "mock"
    assert result["market_results"][0]["market"] == "US"
    assert result["market_results"][0]["baselines"]
    assert result["signal_research"]["research_only"] is True
    assert result["signal_research"]["adoption_permitted"] is False
    assert result["signal_research"]["signal_count"] > 0
    assert result["bias_warnings"]
    assert "시뮬레이션" in result["disclaimer"]


def test_rule_backtest_uses_saved_risk_profile():
    repository = InMemoryRepository()
    repository.upsert_settings({"risk_profile": "aggressive", "candidate_horizon": "short"})
    repository.upsert_candidate_universe(
        {
            "report_type": "global",
            "market": "US",
            "ticker": "AAPL",
            "name": "Apple",
            "currency": "USD",
            "source": "test",
        }
    )

    class FixedTechnicalAnalysis:
        def analyze(self, *_args, **_kwargs):
            return SimpleNamespace(technical_score=70)

    service = RuleBacktestService(
        repository,
        FakeMarketData(),
        technical_analysis_service=FixedTechnicalAnalysis(),
    )

    result = service.run("global", limit=1)

    assert [group["action"] for group in result["groups"]] == ["BUY"]
    assert result["forward_days"] == 5


def test_rule_backtest_builds_walk_forward_and_regime_results():
    repository = InMemoryRepository()
    repository.upsert_candidate_universe(
        {
            "report_type": "global",
            "market": "US",
            "ticker": "AAPL",
            "name": "Apple",
            "currency": "USD",
            "source": "test",
        }
    )

    result = RuleBacktestService(repository, FakeMarketData(size=760)).run("global")

    assert result["walk_forward"]["fold_count"] >= 2
    assert result["walk_forward"]["embargo_samples"] >= 1
    assert result["regime_groups"]
    assert sum(row["sample_count"] for row in result["regime_groups"]) == result["sample_count"]
    assert result["signal_research"]["walk_forward"]["fold_count"] >= 3


def test_research_folds_use_full_horizon_embargo_and_date_boundaries():
    service = RuleBacktestService(InMemoryRepository(), FakeMarketData())
    samples = []
    for day in range(80):
        decision_date = str((pd.Timestamp("2025-01-01") + pd.Timedelta(days=day)).date())
        label_end_date = str((pd.Timestamp("2025-01-01") + pd.Timedelta(days=day + 20)).date())
        for ticker in ("AAA", "BBB"):
            samples.append(
                {
                    "date": decision_date,
                    "label_end_date": label_end_date,
                    "ticker": ticker,
                }
            )

    folds = service._research_folds(samples, forward_days=20, sample_step=1)

    assert folds
    assert all("test_dates" in fold and "test_indices" not in fold for fold in folds)
    assert all(len(fold["test_dates"]) == len(set(fold["test_dates"])) for fold in folds)


def test_same_date_tickers_are_equal_weighted_before_compounding():
    service = RuleBacktestService(InMemoryRepository(), FakeMarketData())
    daily = service._daily_portfolio_samples(
        [
            {
                "date": "2026-01-02",
                "label_end_date": "2026-01-20",
                "gross_return_pct": 10,
                "net_return_pct": 8,
                "turnover": 2,
            },
            {
                "date": "2026-01-02",
                "label_end_date": "2026-01-20",
                "gross_return_pct": -10,
                "net_return_pct": -12,
                "turnover": 2,
            },
        ]
    )

    assert daily == [
        {
            "date": "2026-01-02",
            "label_end_date": "2026-01-20",
            "gross_return_pct": 0.0,
            "net_return_pct": -2.0,
            "turnover": 2.0,
        }
    ]


def test_backtest_enters_at_next_trading_day_price():
    index = pd.date_range("2025-01-02", periods=130, freq="B")
    frame = pd.DataFrame(
        {
            "open": [100.0] * 120 + [200.0] + [100.0] * 9,
            "high": [101.0] * 130,
            "low": [99.0] * 130,
            "close": [100.0] * 124 + [150.0] + [100.0] * 5,
            "volume": [1_000_000.0] * 130,
        },
        index=index,
    )

    class FixedTechnicalAnalysis:
        def analyze(self, *_args, **_kwargs):
            return SimpleNamespace(technical_score=70, trend_label="bull", indicators={})

    service = RuleBacktestService(
        InMemoryRepository(),
        FakeMarketData(),
        technical_analysis_service=FixedTechnicalAnalysis(),
    )
    samples = service._samples_for_frame(
        {"ticker": "AAPL", "name": "Apple", "market": "US", "currency": "USD"},
        frame,
        forward_days=5,
        sample_step=20,
        risk_profile="balanced",
        app_settings=Settings(),
    )

    assert samples[0]["entry_date"] == str(index[120].date())
    assert samples[0]["forward_return"] == -25.0


def test_research_signals_use_only_information_available_at_decision_date():
    service = RuleBacktestService(InMemoryRepository(), FakeMarketData())
    index = pd.date_range("2024-01-02", periods=150, freq="B")
    values = pd.Series(range(100, 250), index=index, dtype=float)
    frame = pd.DataFrame(
        {
            "open": values,
            "high": values + 1,
            "low": values - 1,
            "close": values,
            "volume": values * 100,
        },
        index=index,
    )
    benchmark = frame.copy()
    changed_future = benchmark.copy()
    changed_future.loc[index[120] :, "close"] *= 10
    changed_future.index = changed_future.index.tz_localize("UTC")

    first = service._samples_for_frame(
        {"ticker": "AAPL", "name": "Apple", "market": "US", "currency": "USD"},
        frame,
        forward_days=5,
        sample_step=20,
        risk_profile="balanced",
        app_settings=Settings(),
        benchmark_frame=benchmark,
    )
    second = service._samples_for_frame(
        {"ticker": "AAPL", "name": "Apple", "market": "US", "currency": "USD"},
        frame,
        forward_days=5,
        sample_step=20,
        risk_profile="balanced",
        app_settings=Settings(),
        benchmark_frame=changed_future,
    )

    assert first[0]["signals"] == second[0]["signals"]
    assert first[0]["score"] == second[0]["score"]
    assert first[0]["action"] == second[0]["action"]


def test_research_signal_failure_does_not_interrupt_operational_backtest():
    class FailingResearchTechnicalAnalysis:
        def analyze(self, *_args, **_kwargs):
            return SimpleNamespace(technical_score=70, trend_label="bull", indicators={})

        def calculate_research_signals(self, *_args, **_kwargs):
            raise RuntimeError("research failed")

    service = RuleBacktestService(
        InMemoryRepository(),
        FakeMarketData(),
        technical_analysis_service=FailingResearchTechnicalAnalysis(),
    )
    frame = FakeMarketData(size=130).fetch_price_history().dataframe

    samples = service._samples_for_frame(
        {"ticker": "AAPL", "name": "Apple", "market": "US", "currency": "USD"},
        frame,
        forward_days=5,
        sample_step=20,
        risk_profile="balanced",
        app_settings=Settings(),
    )

    assert samples
    assert samples[0]["signals"] == {}
    assert samples[0]["action"] == "HOLD"


def test_research_evaluation_failure_does_not_interrupt_operational_backtest():
    class FailingSignalResearch:
        def evaluate(self, *_args, **_kwargs):
            raise RuntimeError("evaluation failed")

    repository = InMemoryRepository()
    repository.upsert_candidate_universe(
        {
            "report_type": "global",
            "market": "US",
            "ticker": "AAPL",
            "name": "Apple",
            "currency": "USD",
            "source": "test",
        }
    )
    result = RuleBacktestService(
        repository,
        FakeMarketData(),
        signal_research_service=FailingSignalResearch(),
    ).run("global")

    assert result["groups"]
    assert result["signal_research"]["status"] == "unavailable"
    assert result["signal_research"]["adoption_permitted"] is False


def test_action_cost_and_turnover_match_recommendation_meaning():
    service = RuleBacktestService(InMemoryRepository(), FakeMarketData())

    assert service._action_turnover("BUY") == 2
    assert service._action_turnover("SELL") == 1
    assert service._action_turnover("REDUCE") == 1
    assert service._action_turnover("HOLD") == 0
    assert service._action_turnover("WATCH") == 0

    kr_cost = {
        "fee_pct": 0.2,
        "kr_tax_pct": 0.18,
        "fx_spread_pct": 0.0,
        "slippage_pct": 0.08,
        "total_cost_pct": 0.46,
    }
    assert service._applied_cost_pct("SELL", kr_cost) == 0.32
    assert service._applied_cost_pct("REDUCE", kr_cost) == 0.32
    assert service._applied_cost_pct("HOLD", kr_cost) == 0


def test_overlapping_date_cohorts_are_excluded_from_overall_metrics():
    service = RuleBacktestService(InMemoryRepository(), FakeMarketData())
    samples = [
        {"date": "2026-01-01", "label_end_date": "2026-01-20"},
        {"date": "2026-01-02", "label_end_date": "2026-01-21"},
        {"date": "2026-01-21", "label_end_date": "2026-02-10"},
    ]

    selected = service._non_overlapping_samples(samples)

    assert [row["date"] for row in selected] == ["2026-01-01", "2026-01-21"]


def test_buy_hold_baseline_includes_gap_between_evaluation_windows():
    service = RuleBacktestService(InMemoryRepository(), FakeMarketData())
    empty_cost = {
        "fee_pct": 0.0,
        "kr_tax_pct": 0.0,
        "fx_spread_pct": 0.0,
        "slippage_pct": 0.0,
        "total_cost_pct": 0.0,
    }
    samples = [
        {
            "ticker": "AAPL",
            "date": "2026-01-01",
            "label_end_date": "2026-01-10",
            "entry_price": 100,
            "horizon_price": 110,
            "baselines": {"buy_and_hold": 10, "sma_trend": 10, "simple_momentum": 10},
            "baseline_directions": {"buy_and_hold": 1, "sma_trend": 1, "simple_momentum": 1},
            "cost": empty_cost,
        },
        {
            "ticker": "AAPL",
            "date": "2026-01-11",
            "label_end_date": "2026-01-20",
            "entry_price": 120,
            "horizon_price": 130,
            "baselines": {
                "buy_and_hold": (130 / 120 - 1) * 100,
                "sma_trend": (130 / 120 - 1) * 100,
                "simple_momentum": (130 / 120 - 1) * 100,
            },
            "baseline_directions": {"buy_and_hold": 1, "sma_trend": 1, "simple_momentum": 1},
            "cost": empty_cost,
        },
    ]

    buy_hold = next(
        row for row in service._baseline_summaries(samples) if row["name"] == "buy_and_hold"
    )

    assert buy_hold["metrics"]["gross"]["cumulative_return_pct"] == pytest.approx(30.0)
