"""
Masalas — Suvarn's signal sub-strategies.
Adapted from SuvarnReference for Vrishabh.
"""

import numpy as np
import pandas as pd
import talib


class MeanReversionMasala:
    def __init__(self, df: pd.DataFrame):
        self.close = df["close"].values
        self.high  = df["high"].values
        self.low   = df["low"].values

    def compute_signal(self) -> float:
        if len(self.close) < 200:
            return 0.0

        signal = 0.0

        # StochRSI
        fastk, _ = talib.STOCHRSI(self.close, timeperiod=14, fastk_period=5, fastd_period=3, fastd_matype=0)
        stoch = fastk[-1]
        if not np.isnan(stoch):
            if stoch > 0.8:
                signal -= 1
            elif stoch < 0.2:
                signal += 1

        # CCI
        cci = talib.CCI(self.high, self.low, self.close, timeperiod=20)[-1]
        if not np.isnan(cci):
            if cci > 100:
                signal -= 1.0
            elif cci < -100:
                signal += 1.0

        # Bollinger Bands
        upper, middle, lower = talib.BBANDS(self.close, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
        price      = self.close[-1]
        prev_price = self.close[-2]
        if not (np.isnan(upper[-1]) or np.isnan(lower[-1]) or np.isnan(middle[-1])):
            if price <= lower[-1]:
                signal += 1.0
            elif price >= upper[-1]:
                signal -= 1.0
            if not (np.isnan(lower[-2]) or np.isnan(upper[-2]) or np.isnan(middle[-2])):
                if prev_price <= lower[-2] and price >= middle[-1]:
                    signal += 1.0
                elif prev_price >= upper[-2] and price <= middle[-1]:
                    signal -= 1.0

        # SMA50 vs SMA200
        sma50  = talib.SMA(self.close, timeperiod=50)[-1]
        sma200 = talib.SMA(self.close, timeperiod=200)[-1]
        if not (np.isnan(sma50) or np.isnan(sma200)):
            trend  = "up" if sma50 > sma200 else "down"
            stddev = np.nanstd(self.close[-5:])
            if stddev > 3.7:
                signal += 1.0 if trend == "down" else -1.0

        # SMA20 deviation
        sma20 = talib.SMA(self.close, timeperiod=20)[-1]
        if not np.isnan(sma20) and sma20 != 0:
            deviation = (price - sma20) / sma20
            if deviation > 0.05:
                signal -= 1.0
            elif deviation < -0.05:
                signal += 1.0

        return float(signal)


class TrendMasala:
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()

    def calculate(self) -> float:
        if len(self.df) < 200:
            return 0.0

        close = self.df["close"]
        high  = self.df["high"]
        low   = self.df["low"]

        adx         = talib.ADX(high, low, close, timeperiod=14)
        macd, macdsig, macdhist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        plus_di     = talib.PLUS_DI(high, low, close, timeperiod=14)
        minus_di    = talib.MINUS_DI(high, low, close, timeperiod=14)
        di_diff     = plus_di - minus_di

        ema20  = talib.EMA(close, timeperiod=20)
        ema50  = talib.EMA(close, timeperiod=50)
        ema200 = talib.EMA(close, timeperiod=200)
        slope20  = pd.Series(ema20).diff().fillna(0)
        slope50  = pd.Series(ema50).diff().fillna(0)
        slope200 = pd.Series(ema200).diff().fillna(0)

        atr       = talib.ATR(high, low, close, timeperiod=10)
        hl2       = (high + low) / 2.0
        upperband = hl2 + 3.0 * atr
        lowerband = hl2 - 3.0 * atr
        supertrend = np.where(close > upperband, 1.0, np.where(close < lowerband, -1.0, 0.0))

        def z(x):
            s   = pd.Series(x, index=self.df.index)
            std = s.dropna().std()
            return s / (std + 1e-9) if (std != 0 and not np.isnan(std)) else s.fillna(0.0)

        components = pd.DataFrame({
            "ADX":        (adx / 100.0).fillna(0.0),
            "MACDHist":   z(macdhist),
            "DI_Diff":    z(di_diff),
            "Slope20":    z(slope20),
            "Slope50":    z(slope50),
            "Slope200":   z(slope200),
            "Supertrend": pd.Series(supertrend, index=self.df.index).fillna(0.0),
        }, index=self.df.index).fillna(0.0)

        weights = {"ADX": 1.2, "MACDHist": 1.0, "DI_Diff": 1.0,
                   "Slope20": 0.7, "Slope50": 0.7, "Slope200": 1.0, "Supertrend": 1.2}

        score = sum(components[col] * w for col, w in weights.items()) / sum(weights.values())
        return float(score.iloc[-1])


class MomentumMasala:
    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()

    def calculate(self) -> float:
        close  = self.df["close"]
        high   = self.df["high"]
        low    = self.df["low"]
        volume = self.df["volume"]

        if len(close) < 20:
            return 0.0

        score = 0.0

        roc = talib.ROC(close, timeperiod=10)
        if not np.isnan(roc.iloc[-1]):
            score += 1.0 if roc.iloc[-1] > 2 else (-1.0 if roc.iloc[-1] < -2 else 0.0)

        mom = talib.MOM(close, timeperiod=10)
        if not np.isnan(mom.iloc[-1]):
            score += 1.0 if mom.iloc[-1] > 0 else -1.0

        willr = talib.WILLR(high, low, close, timeperiod=14)
        if not np.isnan(willr.iloc[-1]):
            if willr.iloc[-1] < -80:
                score += 1.0
            elif willr.iloc[-1] > -20:
                score -= 1.0

        obv = talib.OBV(close, volume)
        if len(obv.dropna()) >= 5 and not (np.isnan(obv.iloc[-1]) or np.isnan(obv.iloc[-5])):
            score += 1.0 if obv.iloc[-1] > obv.iloc[-5] else -1.0

        hl = (high - low).replace(0, np.nan)
        mfm = ((close - low) - (high - close)) / hl
        mfv = mfm * volume
        cmf = mfv.rolling(20).sum() / volume.rolling(20).sum()
        if not np.isnan(cmf.iloc[-1]):
            score += 1.0 if cmf.iloc[-1] > 0 else -1.0

        return float(score)


def whale_movement_masala(df: pd.DataFrame) -> float:
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    if len(close) < 35:
        return 0.0

    score = 0.0

    ad = talib.AD(high, low, close, volume)
    if not (np.isnan(ad.iloc[-1]) or np.isnan(ad.iloc[-2])):
        score += 1.0 if ad.iloc[-1] > ad.iloc[-2] else -1.0

    hl  = (high - low).replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / hl
    mfv = mfm * volume
    cmf = mfv.rolling(20).sum() / volume.rolling(20).sum()
    if not np.isnan(cmf.iloc[-1]):
        score += 1.0 if cmf.iloc[-1] > 0 else -1.0

    obv = talib.OBV(close, volume)
    if not (np.isnan(obv.iloc[-1]) or np.isnan(obv.iloc[-2])):
        score += 1.0 if obv.iloc[-1] > obv.iloc[-2] else -1.0

    vwap = ((high + low + close) / 3.0 * volume).cumsum() / volume.cumsum()
    if not (np.isnan(vwap.iloc[-1]) or np.isnan(close.iloc[-1])):
        score += 1.0 if close.iloc[-1] > vwap.iloc[-1] else -1.0

    macd, macksig, _ = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    if not (np.isnan(macd.iloc[-1]) or np.isnan(macksig.iloc[-1])):
        score += 1.0 if macd.iloc[-1] > macksig.iloc[-1] else -1.0

    mfi = talib.MFI(high, low, close, volume, timeperiod=14)
    if not np.isnan(mfi.iloc[-1]):
        score += 1.0 if mfi.iloc[-1] > 50 else -1.0

    return float(score)
