"""
RegimeClassifier — adapted from Suvarn's classi.py
Classifies market regime using 28-bar window.
"""

import numpy as np
import pandas as pd
import talib


REGIMES = ("UP", "DOWN", "RANGE", "BREAKOUT", "SLEEPY", "CHOPPY", "WHALE")

REGIME_THRESHOLDS = {
    "UP":       1.3439356517951127,
    "DOWN":     3.1695083872890373,
    "RANGE":    4.143705431532906,
    "BREAKOUT": 2.4937810936812306,
    "SLEEPY":   0.5123198380380094,
    "CHOPPY":   1.3870943791432953,
    "WHALE":    1.7391220822447164,
}

REGIME_WEIGHTS = {
    "UP":       {"meanrev": 2.28, "trend": 0.61, "momentum": 0.57, "whales": 1.99},
    "DOWN":     {"meanrev": 0.25, "trend": 1.80, "momentum": 1.68, "whales": 0.60},
    "RANGE":    {"meanrev": 1.52, "trend": 0.11, "momentum": 0.45, "whales": 1.46},
    "BREAKOUT": {"meanrev": 2.33, "trend": 1.19, "momentum": 2.44, "whales": 1.10},
    "SLEEPY":   {"meanrev": 1.62, "trend": 0.41, "momentum": 1.35, "whales": 1.96},
    "CHOPPY":   {"meanrev": 0.90, "trend": 0.06, "momentum": 0.63, "whales": 1.85},
    "WHALE":    {"meanrev": 0.65, "trend": 2.43, "momentum": 2.18, "whales": 2.15},
}

REGIME_DESCRIPTIONS = {
    "UP":       "Strong uptrend — SMA50 > SMA200, ADX > 25, +5% over 28d",
    "DOWN":     "Strong downtrend — SMA50 < SMA200, ADX > 25, -5% over 28d",
    "RANGE":    "Ranging market — moderate volatility, weak trend",
    "BREAKOUT": "Breakout — ATR expanding, price at 60-day high/low",
    "SLEEPY":   "Low volatility sideways — ATR at lows",
    "CHOPPY":   "Choppy/erratic — high daily swings, weak direction",
    "WHALE":    "Institutional activity — volume spike + wide-range bar",
}


class RegimeClassifier:
    def __init__(self, df: pd.DataFrame):
        """df must have lowercase columns: close, high, low, volume."""
        self.df = df

    def classify(self, end_date=None) -> str:
        if end_date is not None:
            df_slice = self.df.loc[:end_date].tail(28)
        else:
            df_slice = self.df.tail(28)

        if len(df_slice) < 28:
            return "RANGE"

        close  = df_slice["close"]
        high   = df_slice["high"]
        low    = df_slice["low"]
        volume = df_slice["volume"]

        returns_28  = (close.iloc[-1] - close.iloc[0]) / close.iloc[0] * 100
        adx         = talib.ADX(high, low, close, timeperiod=14).iloc[-1]
        atr         = talib.ATR(high, low, close, timeperiod=14)
        atr_change  = atr.iloc[-1] / atr.mean()
        vol_spike   = volume.iloc[-1] / volume.mean()

        sma50  = talib.SMA(close, timeperiod=50)
        sma200 = talib.SMA(close, timeperiod=200)

        # Whale first (volume spike + wide candle)
        if vol_spike > 3 and (high.iloc[-1] - low.iloc[-1]) > 2 * atr.iloc[-1]:
            return "WHALE"

        # Breakout (ATR expanding + price at extreme)
        if atr_change > 1.5 and (
            close.iloc[-1] >= close.rolling(60).max().iloc[-1]
            or close.iloc[-1] <= close.rolling(60).min().iloc[-1]
        ):
            return "BREAKOUT"

        # Strong trends
        if not (np.isnan(sma50.iloc[-1]) or np.isnan(sma200.iloc[-1])):
            if sma50.iloc[-1] > sma200.iloc[-1] and returns_28 > 5 and adx > 25:
                return "UP"
            if sma50.iloc[-1] < sma200.iloc[-1] and returns_28 < -5 and adx > 25:
                return "DOWN"

        # Sleepy / Range
        if abs(returns_28) < 3 and adx < 20:
            atr_pct = np.percentile(atr.dropna(), 10) if len(atr.dropna()) >= 10 else atr.mean() * 0.5
            return "SLEEPY" if atr.iloc[-1] < atr_pct else "RANGE"

        if adx < 15 and close.pct_change().abs().rolling(5).mean().iloc[-1] > 0.02:
            return "CHOPPY"

        return "RANGE"
