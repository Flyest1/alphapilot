from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class TechnicalAnalysisResult:
    ticker: str
    current_price: float | None
    indicators: dict[str, float | None]
    technical_score: int
    score_breakdown: dict[str, int]
    trend_label: str
    data_quality_note: str


class TechnicalAnalysisService:
    def calculate_indicators(self, dataframe: pd.DataFrame) -> pd.DataFrame:
        frame = dataframe.copy()
        if frame.empty:
            return frame

        close = frame["close"]
        high = frame["high"] if "high" in frame else close
        low = frame["low"] if "low" in frame else close
        volume = frame["volume"] if "volume" in frame else pd.Series(0, index=frame.index)

        frame["sma_5"] = close.rolling(window=5).mean()
        frame["sma_20"] = close.rolling(window=20).mean()
        frame["sma_60"] = close.rolling(window=60).mean()
        frame["sma_120"] = close.rolling(window=120).mean()
        frame["ema_12"] = close.ewm(span=12, adjust=False).mean()
        frame["ema_26"] = close.ewm(span=26, adjust=False).mean()
        frame["rsi_14"] = self._rsi_wilder(close, 14)
        frame["atr_14"] = self._atr_wilder(high, low, close, 14)
        frame["macd"] = frame["ema_12"] - frame["ema_26"]
        frame["macd_signal"] = frame["macd"].ewm(span=9, adjust=False).mean()
        frame["bb_middle"] = frame["sma_20"]
        rolling_std = close.rolling(window=20).std(ddof=0)
        frame["bb_upper"] = frame["bb_middle"] + (rolling_std * 2)
        frame["bb_lower"] = frame["bb_middle"] - (rolling_std * 2)
        volume_ma_5 = volume.rolling(window=5).mean()
        volume_ma_20 = volume.rolling(window=20).mean()
        frame["volume_change_rate"] = ((volume_ma_5 / volume_ma_20) - 1) * 100
        frame["high_20"] = high.rolling(window=20).max()
        frame["low_20"] = low.rolling(window=20).min()
        return frame

    def analyze(self, ticker: str, dataframe: pd.DataFrame) -> TechnicalAnalysisResult:
        if dataframe.empty or len(dataframe) < 20:
            return TechnicalAnalysisResult(
                ticker=ticker,
                current_price=None,
                indicators={},
                technical_score=0,
                score_breakdown={
                    "trend": 0,
                    "momentum": 0,
                    "volume": 0,
                    "volatility": 0,
                    "price_position": 0,
                },
                trend_label="data-limited",
                data_quality_note="insufficient market data",
            )

        indicators = self.calculate_indicators(dataframe)
        latest = indicators.iloc[-1]
        indicator_values = {
            key: self._to_optional_float(latest.get(key))
            for key in (
                "sma_5",
                "sma_20",
                "sma_60",
                "sma_120",
                "ema_12",
                "ema_26",
                "rsi_14",
                "atr_14",
                "macd",
                "macd_signal",
                "bb_middle",
                "bb_upper",
                "bb_lower",
                "volume_change_rate",
                "high_20",
                "low_20",
            )
        }
        breakdown = self.calculate_score_breakdown(latest)
        score = int(sum(breakdown.values()))
        return TechnicalAnalysisResult(
            ticker=ticker,
            current_price=self._to_optional_float(latest.get("close")),
            indicators=indicator_values,
            technical_score=max(0, min(100, score)),
            score_breakdown=breakdown,
            trend_label=self.score_label(score),
            data_quality_note="ok",
        )

    def calculate_score_breakdown(self, latest: pd.Series) -> dict[str, int]:
        close = self._numeric(latest.get("close"))
        sma_5 = self._numeric(latest.get("sma_5"))
        sma_20 = self._numeric(latest.get("sma_20"))
        sma_60 = self._numeric(latest.get("sma_60"))
        sma_120 = self._numeric(latest.get("sma_120"))
        rsi = self._numeric(latest.get("rsi_14"))
        macd = self._numeric(latest.get("macd"))
        signal = self._numeric(latest.get("macd_signal"))
        volume_rate = self._numeric(latest.get("volume_change_rate"))
        bb_upper = self._numeric(latest.get("bb_upper"))
        bb_lower = self._numeric(latest.get("bb_lower"))
        high_20 = self._numeric(latest.get("high_20"))
        low_20 = self._numeric(latest.get("low_20"))

        trend = 0
        trend += 6 if close > sma_5 else 0
        trend += 6 if close > sma_20 else 0
        trend += 6 if sma_5 > sma_20 else 0
        trend += 6 if sma_20 > sma_60 else 0
        trend += 6 if sma_60 > sma_120 else 0

        momentum = 0
        if 50 <= rsi <= 70:
            momentum += 12
        elif 40 <= rsi < 50 or 70 < rsi <= 75:
            momentum += 6
        momentum += 13 if macd > signal else 0

        volume_score = 0
        if volume_rate > 20:
            volume_score = 15
        elif volume_rate > 0:
            volume_score = 10
        elif volume_rate > -20:
            volume_score = 5

        volatility = 0
        if bb_lower < close < bb_upper:
            volatility += 8
        band_width = (bb_upper - bb_lower) / close if close else np.inf
        if band_width <= 0.25:
            volatility += 7
        elif band_width <= 0.4:
            volatility += 4

        price_position = 0
        range_width = high_20 - low_20
        if range_width > 0:
            position = (close - low_20) / range_width
            if 0.55 <= position <= 0.9:
                price_position = 15
            elif 0.35 <= position < 0.55 or 0.9 < position <= 1:
                price_position = 10
            elif 0.15 <= position < 0.35:
                price_position = 5

        return {
            "trend": trend,
            "momentum": momentum,
            "volume": volume_score,
            "volatility": volatility,
            "price_position": price_position,
        }

    def score_label(self, score: int) -> str:
        if score >= 80:
            return "strong bullish setup"
        if score >= 65:
            return "bullish but needs confirmation"
        if score >= 50:
            return "neutral / watch"
        if score >= 35:
            return "weak / reduce risk"
        return "bearish / sell or avoid"

    def _atr_wilder(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int,
    ) -> pd.Series:
        """ATR(14): Wilder 평활 방식의 평균 진폭. 외부 TA 라이브러리 없이 직접 계산한다."""
        previous_close = close.shift(1)
        true_range = pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    def _rsi_wilder(self, close: pd.Series, period: int) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        average_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        average_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        relative_strength = average_gain / average_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + relative_strength))
        rsi = rsi.mask((average_loss == 0) & average_gain.notna(), 100)
        rsi = rsi.mask((average_gain == 0) & (average_loss > 0), 0)
        return rsi

    def _numeric(self, value: Any) -> float:
        parsed = self._to_optional_float(value)
        return parsed if parsed is not None else 0.0

    def _to_optional_float(self, value: Any) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if np.isnan(parsed) or np.isinf(parsed):
            return None
        return parsed
