import numpy as np
import pandas as pd

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
