import numpy as np
import pandas as pd
import pytest

from app.services.technical_analysis_service import TechnicalAnalysisService


def sample_frame(size=130):
    close = pd.Series(range(1, size + 1), dtype=float)
    values = close.to_numpy()
    return pd.DataFrame(
        {
            "open": values,
            "high": values + 1,
            "low": values - 1,
            "close": values,
            "volume": values + 100,
        },
        index=pd.date_range("2026-01-01", periods=size, freq="B"),
    )


def test_calculates_required_indicators_against_known_values():
    service = TechnicalAnalysisService()
    frame = sample_frame()
    indicators = service.calculate_indicators(frame)
    latest = indicators.iloc[-1]

    assert latest["sma_5"] == 128
    assert latest["sma_20"] == 120.5
    assert latest["sma_60"] == 100.5
    assert latest["sma_120"] == 70.5
    assert latest["ema_12"] == frame["close"].ewm(span=12, adjust=False).mean().iloc[-1]
    assert latest["ema_26"] == frame["close"].ewm(span=26, adjust=False).mean().iloc[-1]
    assert latest["rsi_14"] == 100
    assert latest["macd"] == latest["ema_12"] - latest["ema_26"]
    assert latest["macd_signal"] == indicators["macd"].ewm(span=9, adjust=False).mean().iloc[-1]

    expected_std = np.std(np.arange(111, 131), ddof=0)
    assert latest["bb_middle"] == 120.5
    assert latest["bb_upper"] == 120.5 + expected_std * 2
    assert latest["bb_lower"] == 120.5 - expected_std * 2
    assert latest["high_20"] == 131
    assert latest["low_20"] == 110

    volume = frame["volume"]
    expected_volume_rate = ((volume.rolling(5).mean() / volume.rolling(20).mean()) - 1).iloc[
        -1
    ] * 100
    assert latest["volume_change_rate"] == expected_volume_rate


def test_calculates_technical_score_weighting():
    service = TechnicalAnalysisService()
    latest = pd.Series(
        {
            "close": 100,
            "sma_5": 90,
            "sma_20": 80,
            "sma_60": 70,
            "sma_120": 60,
            "rsi_14": 60,
            "macd": 2,
            "macd_signal": 1,
            "volume_change_rate": 25,
            "bb_upper": 112,
            "bb_lower": 92,
            "high_20": 110,
            "low_20": 70,
        }
    )

    breakdown = service.calculate_score_breakdown(latest)

    assert breakdown == {
        "trend": 30,
        "momentum": 25,
        "volume": 15,
        "volatility": 15,
        "price_position": 15,
    }
    assert sum(breakdown.values()) == 100


def test_empty_data_is_data_limited():
    result = TechnicalAnalysisService().analyze("EMPTY", pd.DataFrame())

    assert result.current_price is None
    assert result.indicators == {}
    assert result.technical_score == 0
    assert result.trend_label == "data-limited"
    assert result.data_quality_note == (
        "insufficient market data: requires 120 trading days, received 0"
    )
    assert all(value == 0 for value in result.score_breakdown.values())


@pytest.mark.parametrize("size", [19, 20, 119])
def test_incomplete_score_window_preserves_available_market_data(size):
    frame = sample_frame(size)

    result = TechnicalAnalysisService().analyze("LIMITED", frame)

    assert result.current_price == float(size)
    assert result.technical_score == 0
    assert result.trend_label == "data-limited"
    assert result.data_quality_note.startswith(
        f"insufficient market data: requires 120 trading days, received {size}"
    )
    assert "unavailable indicators:" in result.data_quality_note
    assert result.indicators["ema_12"] is not None
    assert result.indicators["ema_26"] is not None
    assert result.indicators["sma_120"] is None
    assert all(value == 0 for value in result.score_breakdown.values())


def test_120_trading_days_produces_normal_score():
    result = TechnicalAnalysisService().analyze("READY", sample_frame(120))

    assert result.current_price == 120.0
    assert result.indicators["sma_120"] == 60.5
    assert result.technical_score == sum(result.score_breakdown.values())
    assert result.technical_score > 0
    assert result.trend_label != "data-limited"
    assert result.data_quality_note == "ok"


def test_research_signals_do_not_change_when_future_rows_are_added_or_changed():
    service = TechnicalAnalysisService()
    frame = sample_frame(160)

    original_signals = service.calculate_research_signals(frame)
    future = sample_frame(10)
    future.index = pd.date_range(frame.index[-1] + pd.offsets.BDay(), periods=10, freq="B")
    future["close"] = np.linspace(10_000, 20_000, len(future))
    future["high"] = future["close"] + 100
    future["low"] = future["close"] - 100
    future["volume"] = 1_000_000

    expanded_signals = service.calculate_research_signals(pd.concat([frame, future]))
    changed_future = future.copy()
    changed_future["close"] = np.linspace(500, 5, len(changed_future))
    changed_future["high"] = changed_future["close"] + 1
    changed_future["low"] = changed_future["close"] - 1
    changed_future["volume"] = 1
    changed_signals = service.calculate_research_signals(pd.concat([frame, changed_future]))

    pd.testing.assert_frame_equal(original_signals, expanded_signals.loc[frame.index])
    pd.testing.assert_frame_equal(original_signals, changed_signals.loc[frame.index])


def test_research_signals_align_benchmark_before_calculating_relative_strength():
    service = TechnicalAnalysisService()
    asset = sample_frame(100)
    benchmark = sample_frame(90)
    benchmark.index = asset.index[10:]
    benchmark["close"] = np.linspace(100, 190, len(benchmark))

    signals = service.calculate_research_signals(asset, benchmark)
    overlap = asset.index.intersection(benchmark.index)
    first_valid_date = overlap[20]
    expected = (
        (asset.loc[first_valid_date, "close"] / asset.loc[overlap[0], "close"])
        / (benchmark.loc[first_valid_date, "close"] / benchmark.loc[overlap[0], "close"])
    ) - 1

    assert signals.loc[overlap[:20], "relative_strength_20"].isna().all()
    assert signals.loc[first_valid_date, "relative_strength_20"] == pytest.approx(expected)
    assert signals.loc[asset.index[:10], "relative_strength_20"].isna().all()
    assert signals["relative_strength_60"].notna().sum() == len(overlap) - 60


def test_research_signals_handle_constant_prices_zero_volume_and_120_day_boundaries():
    service = TechnicalAnalysisService()
    index = pd.date_range("2026-01-01", periods=133, freq="B")
    frame = pd.DataFrame(
        {
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 0.0,
        },
        index=index,
    )

    signals = service.calculate_research_signals(frame)

    assert signals.loc[index[119], "return_120d"] != signals.loc[index[119], "return_120d"]
    assert signals.loc[index[120], "return_120d"] == 0
    assert signals.loc[index[120], "momentum_consistency"] == 0
    assert (
        signals.loc[index[19], "relative_volume_20"] != signals.loc[index[19], "relative_volume_20"]
    )
    assert signals.loc[index[19], "average_traded_value_20"] == 0
    assert signals.loc[index[20], "realized_volatility_20"] == 0
    assert signals.loc[index[59], "drawdown_60"] == 0
    assert (
        signals.loc[index[131], "atr_percentile_120"]
        != signals.loc[index[131], "atr_percentile_120"]
    )
    assert signals.loc[index[132], "atr_percentile_120"] == 1
    assert signals["relative_strength_20"].map(lambda value: value is None).all()
    assert signals["relative_strength_60"].map(lambda value: value is None).all()


def test_research_signal_calculation_preserves_existing_analyze_result():
    service = TechnicalAnalysisService()
    frame = sample_frame(130)
    before = service.analyze("UNCHANGED", frame)

    service.calculate_research_signals(frame)
    after = service.analyze("UNCHANGED", frame)

    assert after == before
