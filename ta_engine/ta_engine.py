"""
TAEngine — Vrishabh's technical analysis layer.

For each ticker:
  1. Fetch OHLCV from cache (via MarketDataPipeline)
  2. Classify regime
  3. Run 4 masalas with regime-weighted scoring
  4. Detect named patterns + plain-English explanation
  5. Return TASignal
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
import talib
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from config import TA_SCORE_BUY_THRESHOLD, TA_SCORE_SELL_THRESHOLD
from pipelines.market_data import fetch_ohlcv, fetch_all_ohlcv
from .masalas import MeanReversionMasala, TrendMasala, MomentumMasala, whale_movement_masala
from .regime import RegimeClassifier, REGIME_THRESHOLDS, REGIME_WEIGHTS, REGIME_DESCRIPTIONS


# ──────────────────────────────────────────────
# DATA CLASSES
# ──────────────────────────────────────────────

@dataclass
class TASignal:
    ticker:           str
    score:            float
    regime:           str
    regime_desc:      str
    threshold:        float
    suggested_action: str          # "BUY" | "SELL" | "HOLD"
    confidence:       float        # 0–1
    last_close:       float
    masala_scores:    Dict[str, float] = field(default_factory=dict)
    patterns:         List[dict]       = field(default_factory=list)   # [{name, direction, explanation}]
    support:          Optional[float]  = None
    resistance:       Optional[float]  = None

    def to_dict(self) -> dict:
        return {
            "ticker":            self.ticker,
            "score":             round(self.score, 4),
            "regime":            self.regime,
            "regime_desc":       self.regime_desc,
            "threshold":         self.threshold,
            "suggested_action":  self.suggested_action,
            "confidence":        round(self.confidence, 3),
            "last_close":        self.last_close,
            "masala_scores":     {k: round(v, 4) for k, v in self.masala_scores.items()},
            "patterns":          self.patterns,
            "support":           self.support,
            "resistance":        self.resistance,
        }


# ──────────────────────────────────────────────
# PATTERN DETECTION
# ──────────────────────────────────────────────

def _detect_patterns(df: pd.DataFrame) -> List[dict]:
    """
    Detects common chart patterns using TA-Lib candlestick + indicator logic.
    Returns a list of {name, direction, explanation, strength}.
    """
    patterns = []
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    open_  = df["open"]
    volume = df["volume"]

    price = float(close.iloc[-1])

    # ── Bollinger Band squeeze / breakout ───────────────────────
    upper, mid, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
    bw = (upper - lower) / mid   # bandwidth
    if len(bw.dropna()) >= 20:
        bw_pct = float(bw.rank(pct=True).iloc[-1])
        if bw_pct < 0.2:
            patterns.append({
                "name": "Bollinger Squeeze",
                "direction": "neutral",
                "explanation": "Bands are tightly compressed — volatility at lows. A sharp move (breakout or breakdown) is likely imminent.",
                "strength": 0.7,
            })
        elif price > float(upper.iloc[-1]):
            patterns.append({
                "name": "Bollinger Breakout (Upper)",
                "direction": "bearish",
                "explanation": "Price closed above the upper Bollinger Band — overbought signal. Watch for pullback.",
                "strength": 0.6,
            })
        elif price < float(lower.iloc[-1]):
            patterns.append({
                "name": "Bollinger Breakdown (Lower)",
                "direction": "bullish",
                "explanation": "Price closed below the lower Bollinger Band — oversold signal. Bounce likely.",
                "strength": 0.6,
            })

    # ── MACD crossover ───────────────────────────────────────────
    macd_line, signal_line, hist = talib.MACD(close, 12, 26, 9)
    if len(hist.dropna()) >= 2:
        h0 = float(hist.iloc[-1])
        h1 = float(hist.iloc[-2])
        if h1 < 0 < h0:
            patterns.append({
                "name": "MACD Bullish Crossover",
                "direction": "bullish",
                "explanation": "MACD line just crossed above the signal line — momentum turning positive.",
                "strength": 0.75,
            })
        elif h1 > 0 > h0:
            patterns.append({
                "name": "MACD Bearish Crossover",
                "direction": "bearish",
                "explanation": "MACD line just crossed below the signal line — momentum turning negative.",
                "strength": 0.75,
            })

    # ── Golden / Death Cross ─────────────────────────────────────
    if len(close) >= 200:
        sma50  = talib.SMA(close, 50)
        sma200 = talib.SMA(close, 200)
        if not (np.isnan(sma50.iloc[-1]) or np.isnan(sma200.iloc[-1]) or
                np.isnan(sma50.iloc[-2]) or np.isnan(sma200.iloc[-2])):
            if sma50.iloc[-2] < sma200.iloc[-2] and sma50.iloc[-1] > sma200.iloc[-1]:
                patterns.append({
                    "name": "Golden Cross",
                    "direction": "bullish",
                    "explanation": "50-DMA crossed above 200-DMA — classic long-term bullish signal.",
                    "strength": 0.9,
                })
            elif sma50.iloc[-2] > sma200.iloc[-2] and sma50.iloc[-1] < sma200.iloc[-1]:
                patterns.append({
                    "name": "Death Cross",
                    "direction": "bearish",
                    "explanation": "50-DMA crossed below 200-DMA — long-term bearish signal.",
                    "strength": 0.9,
                })

    # ── RSI divergence / overbought / oversold ───────────────────
    rsi = talib.RSI(close, timeperiod=14)
    if not np.isnan(rsi.iloc[-1]):
        r = float(rsi.iloc[-1])
        if r > 75:
            patterns.append({
                "name": "RSI Overbought",
                "direction": "bearish",
                "explanation": f"RSI at {r:.1f} — significantly overbought. Risk of reversal.",
                "strength": 0.65,
            })
        elif r < 25:
            patterns.append({
                "name": "RSI Oversold",
                "direction": "bullish",
                "explanation": f"RSI at {r:.1f} — significantly oversold. Bounce opportunity.",
                "strength": 0.65,
            })

    # ── Volume breakout ──────────────────────────────────────────
    avg_vol = float(volume.rolling(20).mean().iloc[-1])
    cur_vol = float(volume.iloc[-1])
    if avg_vol > 0 and cur_vol > 2.5 * avg_vol:
        direction = "bullish" if close.iloc[-1] > close.iloc[-2] else "bearish"
        patterns.append({
            "name": "Volume Spike",
            "direction": direction,
            "explanation": f"Volume {cur_vol / avg_vol:.1f}x above 20-day average — strong institutional interest.",
            "strength": 0.8,
        })

    # ── Candlestick patterns via TA-Lib ──────────────────────────
    candle_checks = [
        ("Hammer",           talib.CDLHAMMER,      "bullish",  "Hammer candle — potential reversal from downtrend."),
        ("Shooting Star",    talib.CDLSHOOTINGSTAR, "bearish",  "Shooting star — potential reversal from uptrend."),
        ("Doji",             talib.CDLDOJI,         "neutral",  "Doji candle — indecision between buyers and sellers."),
        ("Engulfing Bull",   talib.CDLENGULFING,    "bullish",  "Bullish engulfing pattern — strong buying pressure."),
        ("Morning Star",     talib.CDLMORNINGSTAR,  "bullish",  "Morning star — strong 3-candle bullish reversal."),
        ("Evening Star",     talib.CDLEVENINGSTAR,  "bearish",  "Evening star — strong 3-candle bearish reversal."),
        ("Three White Soldiers", talib.CDL3WHITESOLDIERS, "bullish", "Three white soldiers — sustained buying over 3 days."),
        ("Three Black Crows",    talib.CDL3BLACKCROWS,    "bearish", "Three black crows — sustained selling over 3 days."),
    ]

    o = open_.values
    h = high.values
    l = low.values
    c = close.values

    for name, func, direction, explanation in candle_checks:
        try:
            result = func(o, h, l, c)
            if result[-1] != 0:
                patterns.append({
                    "name":        name,
                    "direction":   direction,
                    "explanation": explanation,
                    "strength":    0.7,
                })
        except Exception:
            pass

    return patterns


# ──────────────────────────────────────────────
# SUPPORT / RESISTANCE
# ──────────────────────────────────────────────

def _support_resistance(df: pd.DataFrame, lookback: int = 50):
    recent  = df.tail(lookback)
    support    = float(recent["low"].min())
    resistance = float(recent["high"].max())
    return support, resistance


# ──────────────────────────────────────────────
# TA ENGINE
# ──────────────────────────────────────────────

class TAEngine:
    """
    Runs technical analysis for a given ticker's OHLCV DataFrame.
    """

    _regime_state: Dict[str, str]  = {}
    _regime_recalc: Dict[str, int] = {}

    def analyse(self, ticker: str, df: Optional[pd.DataFrame] = None) -> Optional[TASignal]:
        """
        Analyse a single ticker. Fetches data if df not provided.
        Returns TASignal or None if insufficient data.
        """
        if df is None:
            df = fetch_ohlcv(ticker)
        if df is None or len(df) < 200:
            return None

        # ── Regime ────────────────────────────────────────────────
        bar_idx = len(df)
        regime  = self._regime_state.get(ticker)

        if regime is None or bar_idx >= self._regime_recalc.get(ticker, 0):
            try:
                rc     = RegimeClassifier(df)
                regime = rc.classify()
            except Exception:
                regime = "RANGE"
            self._regime_state[ticker]  = regime
            self._regime_recalc[ticker] = bar_idx + 28

        # ── Masalas ───────────────────────────────────────────────
        try:
            mr  = MeanReversionMasala(df).compute_signal()
            tr  = TrendMasala(df).calculate()
            mom = MomentumMasala(df).calculate()
            wh  = whale_movement_masala(df)
        except Exception:
            return None

        weights = REGIME_WEIGHTS.get(regime, {"meanrev": 1.0, "trend": 1.0, "momentum": 1.0, "whales": 1.0})
        score   = (
            mr  * weights["meanrev"]
            + tr  * weights["trend"]
            + mom * weights["momentum"]
            + wh  * weights["whales"]
        )

        threshold = REGIME_THRESHOLDS.get(regime, 3.0)

        if score >= threshold:
            action = "BUY"
        elif score <= 0.0:
            action = "SELL"
        else:
            action = "HOLD"

        # Confidence: C = 65 + 35*(1 - e^(-k*(S-T))) / 100, k=0.7
        # BUY:  score > threshold  → C starts at 65% at threshold, rises to 100%
        # SELL: score < 0          → mirrored; starts at 65% at 0, rises as score goes negative
        # HOLD: linear 40–65% as score goes from 0 → threshold
        _k = 0.7
        if action == "BUY":
            conf = (65.0 + 35.0 * (1.0 - math.exp(-_k * (score - threshold)))) / 100.0
        elif action == "SELL":
            conf = (65.0 + 35.0 * (1.0 - math.exp(-_k * (-score)))) / 100.0
        else:
            conf = (40.0 + 25.0 * (score / (threshold + 1e-6))) / 100.0
        conf = max(0.0, min(1.0, conf))

        # ── Patterns + S/R ────────────────────────────────────────
        patterns = _detect_patterns(df)
        support, resistance = _support_resistance(df)

        return TASignal(
            ticker           = ticker,
            score            = score,
            regime           = regime,
            regime_desc      = REGIME_DESCRIPTIONS.get(regime, ""),
            threshold        = threshold,
            suggested_action = action,
            confidence       = conf,
            last_close       = float(df["close"].iloc[-1]),
            masala_scores    = {"meanrev": mr, "trend": tr, "momentum": mom, "whales": wh},
            patterns         = patterns,
            support          = support,
            resistance       = resistance,
        )

    def analyse_many(self, tickers: List[str], max_workers: int = 8) -> Dict[str, TASignal]:
        """Concurrent analysis across tickers. Returns {ticker: TASignal}."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        df_map = fetch_all_ohlcv(tickers, max_workers=max_workers)
        results = {}

        for ticker, df in df_map.items():
            sig = self.analyse(ticker, df)
            if sig:
                results[ticker] = sig

        return results
