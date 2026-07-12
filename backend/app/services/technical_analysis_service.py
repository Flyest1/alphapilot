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
    MINIMUM_SCORE_TRADING_DAYS = 120
    SCORE_BREAKDOWN_KEYS = (
        "trend",
        "momentum",
        "volume",
        "volatility",
        "price_position",
    )
    INDICATOR_KEYS = (
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
    RESEARCH_SIGNAL_COLUMNS = (
        "sma_20_slope_normalized",
        "return_5d",
        "return_20d",
        "return_60d",
        "return_120d",
        "momentum_consistency",
        "relative_volume_20",
        "average_traded_value_20",
        "realized_volatility_20",
        "atr_percentile_120",
        "drawdown_60",
        "relative_strength_20",
        "relative_strength_60",
    )

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

    def calculate_research_signals(
        self,
        dataframe: pd.DataFrame,
        benchmark: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Calculate trailing-only research features without changing production scores."""
        signals = pd.DataFrame(index=dataframe.index, columns=self.RESEARCH_SIGNAL_COLUMNS)
        if dataframe.empty:
            return signals

        close = pd.to_numeric(dataframe["close"], errors="coerce")
        high = pd.to_numeric(dataframe["high"], errors="coerce") if "high" in dataframe else close
        low = pd.to_numeric(dataframe["low"], errors="coerce") if "low" in dataframe else close
        volume = (
            pd.to_numeric(dataframe["volume"], errors="coerce")
            if "volume" in dataframe
            else pd.Series(0.0, index=dataframe.index)
        )

        sma_20 = close.rolling(window=20).mean()
        signals["sma_20_slope_normalized"] = (sma_20 / sma_20.shift(20)) - 1

        returns = pd.DataFrame(
            {
                "return_5d": close.pct_change(periods=5, fill_method=None),
                "return_20d": close.pct_change(periods=20, fill_method=None),
                "return_60d": close.pct_change(periods=60, fill_method=None),
                "return_120d": close.pct_change(periods=120, fill_method=None),
            },
            index=dataframe.index,
        )
        signals[returns.columns] = returns
        signals["momentum_consistency"] = returns.gt(0).where(returns.notna()).mean(axis=1)
        signals.loc[returns.isna().any(axis=1), "momentum_consistency"] = np.nan

        volume_mean_20 = volume.rolling(window=20).mean()
        signals["relative_volume_20"] = volume / volume_mean_20.replace(0, np.nan)
        signals["average_traded_value_20"] = (close * volume).rolling(window=20).mean()

        daily_returns = close.pct_change(fill_method=None)
        signals["realized_volatility_20"] = daily_returns.rolling(window=20).std(ddof=0) * np.sqrt(
            252
        )
        atr_14 = self._atr_wilder(high, low, close, 14)
        signals["atr_percentile_120"] = atr_14.rolling(window=120).apply(
            self._last_value_percentile,
            raw=False,
        )
        signals["drawdown_60"] = (close / close.rolling(window=60).max()) - 1

        if benchmark is None:
            signals["relative_strength_20"] = None
            signals["relative_strength_60"] = None
            return signals

        benchmark_close = pd.to_numeric(benchmark["close"], errors="coerce")
        aligned = pd.concat(
            [close.rename("asset"), benchmark_close.rename("benchmark")],
            axis=1,
            join="inner",
        ).dropna()
        for period in (20, 60):
            relative_strength = (
                (aligned["asset"] / aligned["asset"].shift(period))
                / (aligned["benchmark"] / aligned["benchmark"].shift(period))
            ) - 1
            signals.loc[relative_strength.index, f"relative_strength_{period}"] = relative_strength
        return signals

    def analyze(self, ticker: str, dataframe: pd.DataFrame) -> TechnicalAnalysisResult:
        if dataframe.empty:
            return TechnicalAnalysisResult(
                ticker=ticker,
                current_price=None,
                indicators={},
                technical_score=0,
                score_breakdown=self._empty_score_breakdown(),
                trend_label="data-limited",
                data_quality_note=(
                    "insufficient market data: requires 120 trading days, received 0"
                ),
            )

        indicators = self.calculate_indicators(dataframe)
        latest = indicators.iloc[-1]
        indicator_values = {
            key: self._to_optional_float(latest.get(key)) for key in self.INDICATOR_KEYS
        }
        current_price = self._to_optional_float(latest.get("close"))
        if len(dataframe) < self.MINIMUM_SCORE_TRADING_DAYS:
            unavailable_indicators = [
                key for key, value in indicator_values.items() if value is None
            ]
            unavailable_note = ", ".join(unavailable_indicators) or "none"
            return TechnicalAnalysisResult(
                ticker=ticker,
                current_price=current_price,
                indicators=indicator_values,
                technical_score=0,
                score_breakdown=self._empty_score_breakdown(),
                trend_label="data-limited",
                data_quality_note=(
                    "insufficient market data: requires 120 trading days, "
                    f"received {len(dataframe)}; unavailable indicators: {unavailable_note}"
                ),
            )

        breakdown = self.calculate_score_breakdown(latest)
        score = int(sum(breakdown.values()))
        return TechnicalAnalysisResult(
            ticker=ticker,
            current_price=current_price,
            indicators=indicator_values,
            technical_score=max(0, min(100, score)),
            score_breakdown=breakdown,
            trend_label=self.score_label(score),
            data_quality_note="ok",
        )

    def _empty_score_breakdown(self) -> dict[str, int]:
        return {key: 0 for key in self.SCORE_BREAKDOWN_KEYS}

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

    def _last_value_percentile(self, values: pd.Series) -> float:
        return float((values <= values.iloc[-1]).mean())

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
