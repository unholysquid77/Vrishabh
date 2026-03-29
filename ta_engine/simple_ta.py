"""
Simple TA engine — open-source fallback when Suvarn API is not available.

Strategy: MACD (12/26/9) + Supertrend (14, 3×ATR) + ADX/DI (14) + Bollinger (20, 2σ)
No regime classification — single unified strategy.

Score range: roughly −3.0 to +3.0
  BUY  threshold = 1.5
  SELL threshold = 0.0

All talib outputs are wrapped in pd.Series(np.asarray(...), index=df.index)
to handle both numpy-array and pandas-Series returns from different talib builds.
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
import talib
from typing import Optional


BUY_THRESHOLD  = 1.5
SELL_THRESHOLD = 0.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _s(arr, index) -> pd.Series:
    """Coerce a talib result (numpy or Series) to a pd.Series with df.index."""
    return pd.Series(np.asarray(arr, dtype=float), index=index)


# ── Supertrend ────────────────────────────────────────────────────────────────

def supertrend_series(df: pd.DataFrame, period: int = 14, mult: float = 3.0) -> np.ndarray:
    """
    Compute full Supertrend direction for all bars.
    Returns ndarray of +1 (bullish) or -1 (bearish).
    """
    close = df["close"].values.astype(float)
    high  = df["high"].values.astype(float)
    low   = df["low"].values.astype(float)
    n     = len(close)

    atr = np.asarray(talib.ATR(df["high"], df["low"], df["close"], timeperiod=period), dtype=float)

    hl2         = (high + low) / 2.0
    upper_basic = hl2 + mult * atr
    lower_basic = hl2 - mult * atr

    final_upper = upper_basic.copy()
    final_lower = lower_basic.copy()
    direction   = np.ones(n, dtype=float)

    for i in range(1, n):
        if np.isnan(atr[i]):
            direction[i] = direction[i - 1]
            continue

        final_upper[i] = (
            upper_basic[i]
            if upper_basic[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]
            else final_upper[i - 1]
        )
        final_lower[i] = (
            lower_basic[i]
            if lower_basic[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]
            else final_lower[i - 1]
        )

        if direction[i - 1] == -1 and close[i] > final_upper[i]:
            direction[i] = 1.0
        elif direction[i - 1] == 1 and close[i] < final_lower[i]:
            direction[i] = -1.0
        else:
            direction[i] = direction[i - 1]

    return direction


# ── Component computation ─────────────────────────────────────────────────────

def _compute_components(df: pd.DataFrame) -> dict:
    """
    Compute each indicator component as a full Series aligned to df.index.
    Returns dict of Series + individual latest-bar floats.

    Keys: macd_series, st_series, adx_series, bb_series,
          macd, supertrend, adx, bollinger
    """
    idx   = df.index
    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    # ── MACD histogram normalised by ATR ──────────────────────────────────
    try:
        _, _, hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        atr        = talib.ATR(high, low, close, timeperiod=14)
        hist_s     = _s(hist, idx)
        atr_s      = _s(atr,  idx).replace(0, np.nan)
        macd_comp  = (hist_s / atr_s).clip(-1.0, 1.0).fillna(0.0)
    except Exception:
        macd_comp = pd.Series(0.0, index=idx)

    # ── Supertrend ────────────────────────────────────────────────────────
    try:
        st_comp = _s(supertrend_series(df), idx)
    except Exception:
        st_comp = pd.Series(0.0, index=idx)

    # ── ADX + DI ──────────────────────────────────────────────────────────
    try:
        adx      = _s(talib.ADX(high, low, close, timeperiod=14),      idx)
        plus_di  = _s(talib.PLUS_DI(high, low, close, timeperiod=14),  idx)
        minus_di = _s(talib.MINUS_DI(high, low, close, timeperiod=14), idx)
        strength = ((adx - 15.0) / 25.0).clip(0.0, 1.0).fillna(0.0)
        di_dir   = (plus_di - minus_di).apply(np.sign).fillna(0.0)
        adx_comp = di_dir * strength * 0.5
    except Exception:
        adx_comp = pd.Series(0.0, index=idx)

    # ── Bollinger mean-reversion ───────────────────────────────────────────
    try:
        upper_bb, _, lower_bb = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
        upper_s    = _s(upper_bb, idx)
        lower_s    = _s(lower_bb, idx)
        band_range = (upper_s - lower_s).replace(0, np.nan)
        pct_b      = (close - lower_s) / band_range
        bb_raw     = -(pct_b - 0.5) * 2.0
        bb_comp    = bb_raw.where((pct_b - 0.5).abs() > 0.3, 0.0).fillna(0.0) * 0.5
    except Exception:
        bb_comp = pd.Series(0.0, index=idx)

    return {
        # Full series (for backtest)
        "macd_series": macd_comp,
        "st_series":   st_comp,
        "adx_series":  adx_comp,
        "bb_series":   bb_comp,
        # Latest-bar scalars (for live signal + indicator_scores)
        "macd":        round(float(macd_comp.iloc[-1]), 4),
        "supertrend":  round(float(st_comp.iloc[-1]),   4),
        "adx":         round(float(adx_comp.iloc[-1]),  4),
        "bollinger":   round(float(bb_comp.iloc[-1]),   4),
    }


# ── Vectorized score series (used by backtest) ────────────────────────────────

def score_series(df: pd.DataFrame) -> pd.Series:
    """
    Composite score for every bar in df.  Used by backtest.run().
    Returns pd.Series aligned to df.index.
    """
    comps = _compute_components(df)
    return (
        comps["macd_series"] +
        comps["st_series"]   +
        comps["adx_series"]  +
        comps["bb_series"]
    ).rename("score")


# ── Latest-bar score (live signal) ────────────────────────────────────────────

def score_latest(df: pd.DataFrame) -> float:
    """Score for the most recent bar only."""
    comps = _compute_components(df)
    return comps["macd"] + comps["supertrend"] + comps["adx"] + comps["bollinger"]


# ── Trend state (replaces regime for the simple engine) ──────────────────────

def _trend_state(df: pd.DataFrame) -> tuple[str, str]:
    """
    Lightweight trend state based on SMA crossover + ADX.
    Returns (state_label, description).  Much simpler than RegimeClassifier.
    """
    try:
        close  = df["close"]
        sma50  = talib.SMA(close, timeperiod=50)
        sma200 = talib.SMA(close, timeperiod=200)
        adx    = talib.ADX(df["high"], df["low"], close, timeperiod=14)

        s50  = float(np.asarray(sma50)[-1])
        s200 = float(np.asarray(sma200)[-1])
        adv  = float(np.asarray(adx)[-1])

        if np.isnan(s50) or np.isnan(s200) or np.isnan(adv):
            return "NEUTRAL", "Insufficient data for trend classification."

        trending = adv > 20
        if s50 > s200 and trending:
            return "UPTREND",  "SMA50 > SMA200 with ADX > 20 — confirmed uptrend."
        if s50 < s200 and trending:
            return "DOWNTREND", "SMA50 < SMA200 with ADX > 20 — confirmed downtrend."
        if adv < 15:
            return "RANGING", "ADX < 15 — low-trend, sideways market."
        return "MIXED", "Trend signals are mixed — no clear directional bias."
    except Exception:
        return "NEUTRAL", "Trend state unavailable."


# ── Public: analyse one ticker ────────────────────────────────────────────────

def analyse(ticker: str, df: pd.DataFrame) -> dict:
    """
    Run simple TA on an already-fetched OHLCV DataFrame.
    Returns a TASignal-compatible dict (same schema as Suvarn API response).
    """
    if len(df) < 60:
        return {}

    try:
        comps = _compute_components(df)
        s = comps["macd"] + comps["supertrend"] + comps["adx"] + comps["bollinger"]
    except Exception:
        return {}

    if s >= BUY_THRESHOLD:
        action = "BUY"
    elif s <= SELL_THRESHOLD:
        action = "SELL"
    else:
        action = "HOLD"

    # Confidence — asymptotic formula centred at 0.60 for simple TA
    # (Suvarn starts at 0.65; simple TA is more conservative → base = 0.60)
    # C = 0.60 + 0.40 × (1 − e^(−0.7 × gap))
    # At threshold crossing (gap=0): C = 0.60
    # Deep BUY/SELL (large gap): C approaches 1.0
    k = 0.7
    if action == "BUY":
        gap  = max(s - BUY_THRESHOLD, 0.0)
        conf = (60.0 + 40.0 * (1.0 - math.exp(-k * gap))) / 100.0
    elif action == "SELL":
        gap  = max(-s, 0.0)
        conf = (60.0 + 40.0 * (1.0 - math.exp(-k * gap))) / 100.0
    else:
        conf = 0.50

    # Trend state (replaces regime — no complex regime classification)
    trend, trend_desc = _trend_state(df)

    close      = df["close"]
    last_close = float(close.iloc[-1])
    prev_close = float(close.iloc[-2]) if len(close) >= 2 else None
    pct_change = (
        round((last_close - prev_close) / prev_close * 100, 2)
        if prev_close and prev_close > 0 else None
    )

    support    = float(df.tail(50)["low"].min())
    resistance = float(df.tail(50)["high"].max())
    ticker_clean = ticker.upper().replace(".NS", "")

    return {
        "ticker":            ticker_clean,
        "score":             round(s, 4),
        "regime":            trend,
        "regime_desc":       trend_desc,
        "threshold":         BUY_THRESHOLD,
        "suggested_action":  action,
        "confidence":        round(conf, 4),
        "last_close":        last_close,
        "prev_close":        prev_close,
        "pct_change":        pct_change,
        # Component breakdown — matches masala_scores schema used by Suvarn
        "indicator_scores": {
            "macd":       comps["macd"],
            "supertrend": comps["supertrend"],
            "adx":        comps["adx"],
            "bollinger":  comps["bollinger"],
        },
        "support":           round(support, 2),
        "resistance":        round(resistance, 2),
    }
