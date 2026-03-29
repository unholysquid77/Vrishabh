"""
suvarn_client/ta_client.py — Technical Analysis facade.

Prod mode (SUVARN_API_URL set)  : delegates to the live API.
Local mode (SUVARN_API_URL unset): uses bundled ta_engine (regime + masalas or simple TA).

Adds on top of the scoring engine:
  - per-masala score breakdown
  - pattern detection (Bollinger, MACD crossover, candlesticks, etc.)
  - support / resistance levels

Returns the same TASignal dataclass used across Vrishabh.
"""

from __future__ import annotations

import math
import time
import numpy as np
import pandas as pd
import talib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import requests

from config import TA_SCORE_BUY_THRESHOLD, TA_SCORE_SELL_THRESHOLD
from pipelines.market_data import fetch_ohlcv, fetch_all_ohlcv
from ._loader import SUVARN_API_URL


# ──────────────────────────────────────────────────────────────────────────────
# TASignal (single source of truth for the whole app)
# ──────────────────────────────────────────────────────────────────────────────

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
    prev_close:       Optional[float]  = None
    masala_scores:    Dict[str, float] = field(default_factory=dict)
    patterns:         List[dict]       = field(default_factory=list)
    support:          Optional[float]  = None
    resistance:       Optional[float]  = None

    @property
    def pct_change(self) -> Optional[float]:
        if self.prev_close and self.prev_close > 0:
            return round((self.last_close - self.prev_close) / self.prev_close * 100, 2)
        return None

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
            "prev_close":        self.prev_close,
            "pct_change":        self.pct_change,
            "masala_scores":     {k: round(v, 4) for k, v in self.masala_scores.items()},
            "patterns":          self.patterns,
            "support":           self.support,
            "resistance":        self.resistance,
        }


# ──────────────────────────────────────────────────────────────────────────────
# TA engine loader
# ──────────────────────────────────────────────────────────────────────────────

def _load_simple_ta():
    """Sentinel: signals to caller that only simple TA is available."""
    print("[TAClient] Masalas unavailable — falling back to simple TA (MACD+Supertrend+ADX+BB)")
    return None


def _load_vrishabh_fallback():
    try:
        from ta_engine.masalas import (
            MeanReversionMasala, TrendMasala, MomentumMasala, whale_movement_masala,
        )
        from ta_engine.regime import (
            RegimeClassifier, REGIME_THRESHOLDS, REGIME_WEIGHTS,
        )
    except Exception as e:
        print(f"[SuvarnClient/TA] ta_engine.masalas unavailable ({e!r})")
        return _load_simple_ta()

    def _compute_score(df_slice, regime=None):
        try:
            mr  = MeanReversionMasala(df_slice).compute_signal()
            tr  = TrendMasala(df_slice).calculate()
            mom = MomentumMasala(df_slice).calculate()
            wh  = whale_movement_masala(df_slice)
            w   = REGIME_WEIGHTS.get(regime, {k: 1.0 for k in ("meanrev","trend","momentum","whales")})
            return float(mr * w["meanrev"] + tr * w["trend"]
                         + mom * w["momentum"] + wh * w["whales"])
        except Exception:
            return 0.0

    def _generate_signals(tickers, df_dict, regime_state, next_recalc, lookback=400):
        results = []
        for t in tickers:
            df = df_dict.get(t)
            if df is None or len(df) < 200:
                continue
            df        = df.copy()
            bar_index = len(df)
            df_slice  = df.iloc[-lookback:]

            regime = regime_state.get(t)
            if regime is None or bar_index >= next_recalc.get(t, 0):
                try:
                    regime = RegimeClassifier(df).classify()
                except Exception:
                    regime = "RANGE"
                regime_state[t]  = regime
                next_recalc[t]   = bar_index + 28

            score      = _compute_score(df_slice, regime)
            threshold  = REGIME_THRESHOLDS.get(regime, 3.0)
            last_close = float(df_slice["close"].iloc[-1])
            suggested  = "Buy" if score >= threshold else ("Sell" if score <= 0 else "Hold")
            results.append({"ticker": t, "score": score, "regime": regime,
                             "last_close": last_close, "bar_index": bar_index,
                             "threshold": threshold, "suggested_action": suggested})
        return sorted(results, key=lambda x: x["score"], reverse=True)

    return (_compute_score, _generate_signals,
            (MeanReversionMasala, TrendMasala, MomentumMasala, whale_movement_masala),
            REGIME_THRESHOLDS, REGIME_WEIGHTS, RegimeClassifier)


# Eagerly load local engine (used when SUVARN_API_URL is not set)
_USING_SIMPLE_TA = False

if not SUVARN_API_URL:
    _fallback = _load_vrishabh_fallback()
    if _fallback is None:
        _USING_SIMPLE_TA = True
        _compute_score_for_ticker = _generate_signals = None
        _MR = _TR = _MOM = _WH = None
        _THRESHOLDS = _WEIGHTS = _RegimeClassifier = None
    else:
        (_compute_score_for_ticker, _generate_signals,
         (_MR, _TR, _MOM, _WH),
         _THRESHOLDS, _WEIGHTS, _RegimeClassifier) = _fallback
else:
    # API mode — local engine not needed
    _USING_SIMPLE_TA = False
    _compute_score_for_ticker = _generate_signals = None
    _MR = _TR = _MOM = _WH = None
    _THRESHOLDS = _WEIGHTS = _RegimeClassifier = None


# ──────────────────────────────────────────────────────────────────────────────
# Regime descriptions
# ──────────────────────────────────────────────────────────────────────────────

_REGIME_DESCRIPTIONS = {
    "UP":       "Strong uptrend — SMA50 > SMA200, ADX > 25, +5% over 28d",
    "DOWN":     "Strong downtrend — SMA50 < SMA200, ADX > 25, -5% over 28d",
    "RANGE":    "Ranging market — moderate volatility, weak trend",
    "BREAKOUT": "Breakout — ATR expanding, price at 60-day high/low",
    "SLEEPY":   "Low volatility sideways — ATR at lows",
    "CHOPPY":   "Choppy/erratic — high daily swings, weak direction",
    "WHALE":    "Institutional activity — volume spike + wide-range bar",
}


# ──────────────────────────────────────────────────────────────────────────────
# Per-masala breakdown (always uses whichever masalas were loaded above)
# ──────────────────────────────────────────────────────────────────────────────

def _masala_scores(df_slice: pd.DataFrame) -> Dict[str, float]:
    """Return individual masala raw scores for the TASignal breakdown."""
    try:
        mr  = float(_MR(df_slice).compute_signal())
        tr  = float(_TR(df_slice).calculate())
        mom = float(_MOM(df_slice).calculate())
        wh  = float(_WH(df_slice))
        return {"meanrev": mr, "trend": tr, "momentum": mom, "whales": wh}
    except Exception as e:
        print(f"[SuvarnClient/TA] masala breakdown failed: {e}")
        return {"meanrev": 0.0, "trend": 0.0, "momentum": 0.0, "whales": 0.0}


# ──────────────────────────────────────────────────────────────────────────────
# Pattern detection (Vrishabh-specific, layered on top of Suvarn scoring)
# ──────────────────────────────────────────────────────────────────────────────

def _detect_patternpy(df: pd.DataFrame, window: int = 20) -> List[dict]:
    """Run PatternPy structural detectors. Returns a list of candidates with date + position."""
    try:
        from tradingpatterns.tradingpatterns import (
            detect_head_shoulder, detect_multiple_tops_bottoms,
            detect_triangle_pattern, detect_wedge, detect_channel,
            detect_double_top_bottom,
        )
    except ImportError:
        return []

    pp = df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low',
                             'close': 'Close', 'volume': 'Volume'}).copy()

    DETECTORS = [
        (detect_head_shoulder,        'head_shoulder_pattern',       {
            'Head and Shoulder':         ('bearish', 'Three peaks with higher middle — classic top reversal.'),
            'Inverse Head and Shoulder': ('bullish', 'Three troughs with lower middle — classic bottom reversal.'),
        }),
        (detect_multiple_tops_bottoms, 'multiple_top_bottom_pattern', {
            'Multiple Top':    ('bearish', 'Multiple highs at same level — strong resistance ceiling.'),
            'Multiple Bottom': ('bullish', 'Multiple lows at same level — strong support floor.'),
        }),
        (detect_triangle_pattern, 'triangle_pattern', {
            'Ascending Triangle':  ('bullish', 'Flat top with rising lows — likely upside breakout.'),
            'Descending Triangle': ('bearish', 'Flat bottom with falling highs — likely downside breakdown.'),
        }),
        (detect_wedge, 'wedge_pattern', {
            'Wedge Up':   ('bearish', 'Rising wedge — converging highs/lows tilting up, bearish reversal ahead.'),
            'Wedge Down': ('bullish', 'Falling wedge — converging highs/lows tilting down, bullish reversal ahead.'),
        }),
        (detect_channel, 'channel_pattern', {
            'Channel Up':   ('bullish', 'Upward price channel — trending within defined bull corridor.'),
            'Channel Down': ('bearish', 'Downward price channel — trending within defined bear corridor.'),
        }),
        (detect_double_top_bottom, 'double_pattern', {
            'Double Top':    ('bearish', 'Two peaks at same level — expect breakdown below neckline.'),
            'Double Bottom': ('bullish', 'Two troughs at same level — expect breakout above neckline.'),
        }),
    ]

    import warnings
    candidates: List[tuple] = []   # (abs_pos, pattern_dict)
    for fn, col, meta_map in DETECTORS:
        try:
            tmp = pp.copy()
            tmp[col] = pd.array([pd.NA] * len(tmp), dtype=object)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                result = fn(tmp)
            if col not in result.columns:
                continue
            recent = result[col].iloc[-window:]
            # Walk backward to find the most recent occurrence for this detector
            for i in range(len(recent) - 1, -1, -1):
                v = recent.iloc[i]
                if isinstance(v, str) and v and v in meta_map:
                    meta = meta_map[v]
                    abs_pos = len(df) - window + i
                    date_str = str(recent.index[i])[:10]
                    candidates.append((abs_pos, {
                        'name': v, 'direction': meta[0],
                        'explanation': meta[1], 'strength': 0.8,
                        'date': date_str,
                    }))
                    break  # one per detector type
        except Exception:
            pass
    return candidates


def _detect_patterns(df: pd.DataFrame) -> List[dict]:
    patterns = []
    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    open_  = df["open"]
    volume = df["volume"]
    price  = float(close.iloc[-1])

    # Bollinger squeeze / breakout
    try:
        upper, mid, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
        bw = (upper - lower) / mid
        if len(bw.dropna()) >= 20:
            bw_pct = float(bw.rank(pct=True).iloc[-1])
            if bw_pct < 0.2:
                patterns.append({"name": "Bollinger Squeeze", "direction": "neutral",
                    "explanation": "Bands compressed — a sharp move is imminent.", "strength": 0.7})
            elif price > float(upper.iloc[-1]):
                patterns.append({"name": "Bollinger Breakout (Upper)", "direction": "bearish",
                    "explanation": "Price above upper band — overbought, watch for pullback.", "strength": 0.6})
            elif price < float(lower.iloc[-1]):
                patterns.append({"name": "Bollinger Breakdown (Lower)", "direction": "bullish",
                    "explanation": "Price below lower band — oversold, bounce likely.", "strength": 0.6})
    except Exception:
        pass

    # MACD crossover
    try:
        _, _, hist = talib.MACD(close, 12, 26, 9)
        if len(hist.dropna()) >= 2:
            h0, h1 = float(hist.iloc[-1]), float(hist.iloc[-2])
            if h1 < 0 < h0:
                patterns.append({"name": "MACD Bullish Crossover", "direction": "bullish",
                    "explanation": "MACD crossed above signal — momentum turning positive.", "strength": 0.75})
            elif h1 > 0 > h0:
                patterns.append({"name": "MACD Bearish Crossover", "direction": "bearish",
                    "explanation": "MACD crossed below signal — momentum turning negative.", "strength": 0.75})
    except Exception:
        pass

    # Golden / Death Cross
    try:
        if len(close) >= 200:
            sma50  = talib.SMA(close, 50)
            sma200 = talib.SMA(close, 200)
            v = [sma50.iloc[-1], sma200.iloc[-1], sma50.iloc[-2], sma200.iloc[-2]]
            if not any(np.isnan(x) for x in v):
                if sma50.iloc[-2] < sma200.iloc[-2] and sma50.iloc[-1] > sma200.iloc[-1]:
                    patterns.append({"name": "Golden Cross", "direction": "bullish",
                        "explanation": "50-DMA crossed above 200-DMA — long-term bullish.", "strength": 0.9})
                elif sma50.iloc[-2] > sma200.iloc[-2] and sma50.iloc[-1] < sma200.iloc[-1]:
                    patterns.append({"name": "Death Cross", "direction": "bearish",
                        "explanation": "50-DMA crossed below 200-DMA — long-term bearish.", "strength": 0.9})
    except Exception:
        pass

    # RSI
    try:
        rsi = talib.RSI(close, timeperiod=14)
        if not np.isnan(rsi.iloc[-1]):
            r = float(rsi.iloc[-1])
            if r > 75:
                patterns.append({"name": "RSI Overbought", "direction": "bearish",
                    "explanation": f"RSI at {r:.1f} — overbought, risk of reversal.", "strength": 0.65})
            elif r < 25:
                patterns.append({"name": "RSI Oversold", "direction": "bullish",
                    "explanation": f"RSI at {r:.1f} — oversold, bounce opportunity.", "strength": 0.65})
    except Exception:
        pass

    # Volume spike
    try:
        avg_vol = float(volume.rolling(20).mean().iloc[-1])
        cur_vol = float(volume.iloc[-1])
        if avg_vol > 0 and cur_vol > 2.5 * avg_vol:
            direction = "bullish" if close.iloc[-1] > close.iloc[-2] else "bearish"
            patterns.append({"name": "Volume Spike", "direction": direction,
                "explanation": f"Volume {cur_vol/avg_vol:.1f}x above 20d avg — strong institutional interest.",
                "strength": 0.8})
    except Exception:
        pass

    # TA-Lib candlestick patterns
    try:
        o, h, l, c = open_.values, high.values, low.values, close.values
        for name, func, direction, explanation in [
            ("Hammer",            talib.CDLHAMMER,         "bullish",  "Hammer — potential reversal from downtrend."),
            ("Shooting Star",     talib.CDLSHOOTINGSTAR,   "bearish",  "Shooting star — potential reversal from uptrend."),
            ("Doji",              talib.CDLDOJI,            "neutral",  "Doji — indecision between buyers and sellers."),
            ("Engulfing Bull",    talib.CDLENGULFING,       "bullish",  "Bullish engulfing — strong buying pressure."),
            ("Morning Star",      talib.CDLMORNINGSTAR,     "bullish",  "Morning star — 3-candle bullish reversal."),
            ("Evening Star",      talib.CDLEVENINGSTAR,     "bearish",  "Evening star — 3-candle bearish reversal."),
            ("Three White Soldiers", talib.CDL3WHITESOLDIERS, "bullish", "Three white soldiers — sustained 3-day buying."),
            ("Three Black Crows",    talib.CDL3BLACKCROWS,    "bearish", "Three black crows — sustained 3-day selling."),
        ]:
            try:
                if func(o, h, l, c)[-1] != 0:
                    patterns.append({"name": name, "direction": direction,
                                     "explanation": explanation, "strength": 0.7})
            except Exception:
                pass
    except Exception:
        pass

    # Add date (last bar's date) to all indicator / candlestick patterns
    last_date = str(df.index[-1])[:10]
    for p in patterns:
        p.setdefault('date', last_date)

    # PatternPy structural patterns — candidates are (abs_pos, dict) tuples
    pp_candidates = _detect_patternpy(df)
    existing_names = {p["name"] for p in patterns}
    for _pos, p in pp_candidates:
        if p["name"] not in existing_names:
            patterns.append(p)

    # Return only the single most significant pattern (highest strength)
    if not patterns:
        return []
    best = max(patterns, key=lambda p: p.get("strength", 0))
    return [best]


def _support_resistance(df: pd.DataFrame, lookback: int = 50):
    recent = df.tail(lookback)
    return float(recent["low"].min()), float(recent["high"].max())


# ──────────────────────────────────────────────────────────────────────────────
# Confidence formula (mirrors SuvarnAPI/ta_engine.py)
# C = (65 + 35 * (1 − e^(−0.7 × gap))) / 100   for BUY/SELL
# gap = score − threshold  (BUY)  |  −score  (SELL)
# Returns 0.50 for HOLD.
# ──────────────────────────────────────────────────────────────────────────────

def _confidence(score: float, threshold: float, action: str) -> float:
    if action == "HOLD":
        return 0.50
    if action == "BUY":
        gap = score - threshold
    else:  # SELL
        gap = -score
    gap = max(gap, 0.0)
    return (65.0 + 35.0 * (1.0 - math.exp(-0.7 * gap))) / 100.0


# ──────────────────────────────────────────────────────────────────────────────
# Regime classification helper (uses full df, not just 28 bars)
# ──────────────────────────────────────────────────────────────────────────────

def _classify_regime(df: pd.DataFrame) -> str:
    """Classify regime using the bundled RegimeClassifier."""
    try:
        rc = _RegimeClassifier(df)
        if hasattr(rc, "classify_regime"):
            return rc.classify_regime(end_date=df.index[-1])
        return rc.classify()
    except Exception as e:
        print(f"[TAClient] regime classification failed: {e}")
        return "RANGE"


# ──────────────────────────────────────────────────────────────────────────────
# CLIENT
# ──────────────────────────────────────────────────────────────────────────────

class SuvarnTAClient:
    """
    Technical Analysis client.

    Prod mode (SUVARN_API_URL set)  : calls the TA API for score/regime/masalas.
    Local mode (SUVARN_API_URL unset): uses bundled ta_engine.
    Results are cached in-memory for 120 s to avoid redundant recomputation.
    """

    _regime_state:  Dict[str, str] = {}
    _regime_recalc: Dict[str, int] = {}
    # {ticker: (expire_timestamp, TASignal)}
    _ta_cache: Dict[str, Tuple[float, "TASignal"]] = {}
    _TA_CACHE_TTL = 120.0   # seconds

    # ── Prod-mode helpers ──────────────────────────────────────────────────────

    def _sig_from_api_dict(self, d: dict, df: Optional[pd.DataFrame] = None) -> TASignal:
        """
        Convert the JSON dict returned by Suvarn API /technicals/{ticker}
        into a TASignal.

        df may be optionally passed in for local pattern detection (only used
        when the caller already has OHLCV on hand).  We never fetch OHLCV here
        — that would duplicate the download that Suvarn API already did.
        """
        ticker = d["ticker"]
        action = (d.get("suggested_action") or "HOLD").upper()

        # Patterns — only run locally if OHLCV was explicitly provided
        patterns = _detect_patterns(df) if df is not None and len(df) >= 50 else []
        if df is not None and len(df) >= 50:
            support, resistance = _support_resistance(df)
        else:
            support  = d.get("support")
            resistance = d.get("resistance")

        prev_close = d.get("prev_close")
        if prev_close is None and df is not None and len(df) >= 2:
            prev_close = float(df["close"].iloc[-2])

        return TASignal(
            ticker           = ticker,
            score            = float(d.get("score", 0.0)),
            regime           = d.get("regime", "RANGE"),
            regime_desc      = d.get("regime_desc") or _REGIME_DESCRIPTIONS.get(d.get("regime", "RANGE"), ""),
            threshold        = float(d.get("threshold", 3.0)),
            suggested_action = action,
            confidence       = float(d.get("confidence", 0.50)),
            last_close       = float(d.get("last_close", 0.0)),
            prev_close       = float(prev_close) if prev_close is not None else None,
            masala_scores    = d.get("masala_scores") or {},
            patterns         = patterns,
            support          = float(support) if support is not None else None,
            resistance       = float(resistance) if resistance is not None else None,
        )

    def _analyse_via_api(self, ticker: str) -> Optional[TASignal]:
        """
        Call GET {SUVARN_API_URL}/technicals/{ticker} and return TASignal.
        Suvarn API caches results for 120 s so repeated calls are instant.
        """
        url = f"{SUVARN_API_URL.rstrip('/')}/technicals/{ticker}"
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            d = resp.json()
            if d.get("error"):
                print(f"[SuvarnAPI/TA] {ticker}: {d['error']}")
                return None
            print(f"[SuvarnAPI/TA] {ticker} score={d.get('score', '?')} regime={d.get('regime', '?')} "
                  f"→ {d.get('suggested_action', '?')}")
            return self._sig_from_api_dict(d)   # no df — no extra yfinance call
        except Exception as e:
            print(f"[SuvarnAPI/TA] {ticker} request failed: {e}")
            return None

    def _analyse_many_via_api(self, tickers: List[str]) -> Dict[str, TASignal]:
        """
        Call POST {SUVARN_API_URL}/technicals/bulk and convert each result to
        a TASignal.  No local OHLCV fetch — Suvarn API already did that and
        caches results for 120 s, so repeated calls within the window are free.
        """
        url = f"{SUVARN_API_URL.rstrip('/')}/technicals/bulk"
        try:
            resp = requests.post(url, json={"tickers": tickers}, timeout=60)
            resp.raise_for_status()
            bulk = resp.json()   # dict {ticker: signal_dict | {error: ...}}
        except Exception as e:
            print(f"[SuvarnAPI/TA] bulk request failed: {e}")
            return {}

        # bulk may be a dict (new) or a list (old shape) — normalise to dict
        if isinstance(bulk, list):
            bulk = {d["ticker"]: d for d in bulk if isinstance(d, dict) and "ticker" in d}

        results: Dict[str, TASignal] = {}
        for t, d in bulk.items():
            if not isinstance(d, dict) or d.get("error"):
                continue
            sig = self._sig_from_api_dict(d)   # no df — skip pattern fetch
            results[t] = sig
            print(f"[SuvarnAPI/TA] {t} score={sig.score:.4f} regime={sig.regime} → {sig.suggested_action}")

        return results

    # ── Simple TA path (open-source fallback) ─────────────────────────────────

    def _analyse_simple(self, ticker: str, df: Optional[pd.DataFrame] = None) -> Optional[TASignal]:
        from ta_engine.simple_ta import analyse as _simple
        if df is None:
            df = fetch_ohlcv(ticker)
        if df is None or len(df) < 60:
            return None
        try:
            d = _simple(ticker, df)
        except Exception as e:
            print(f"[SimpleTAEngine] {ticker} score failed: {e}")
            return None
        if not d:
            return None

        # Map indicator_scores → masala_scores (same field name, different keys)
        indicator_scores = d.get("indicator_scores") or {}

        try:
            patterns = _detect_patterns(df)
        except Exception:
            patterns = []
        try:
            support, resistance = _support_resistance(df)
        except Exception:
            support = d.get("support")
            resistance = d.get("resistance")

        sig = TASignal(
            ticker           = d["ticker"],
            score            = d["score"],
            regime           = d["regime"],
            regime_desc      = d["regime_desc"],
            threshold        = d["threshold"],
            suggested_action = d["suggested_action"],
            confidence       = d["confidence"],
            last_close       = d["last_close"],
            prev_close       = d.get("prev_close"),
            masala_scores    = indicator_scores,
            patterns         = patterns,
            support          = float(support) if support is not None else None,
            resistance       = float(resistance) if resistance is not None else None,
        )
        print(f"[SimpleTAEngine] {ticker} score={sig.score:.4f} trend={sig.regime} → {sig.suggested_action}")
        return sig

    def _analyse_many_simple(self, tickers: List[str]) -> Dict[str, TASignal]:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        df_map = fetch_all_ohlcv(tickers, max_workers=8)
        results: Dict[str, TASignal] = {}

        def _worker(t):
            return t, self._analyse_simple(t, df_map.get(t))

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(_worker, t): t for t in tickers}
            for fut in as_completed(futures):
                try:
                    t, sig = fut.result()
                    if sig:
                        results[t] = sig
                except Exception as e:
                    print(f"[SimpleTAEngine] worker error: {e}")

        return results

    # ── Main interface ─────────────────────────────────────────────────────────

    def analyse(self, ticker: str, df: Optional[pd.DataFrame] = None) -> Optional[TASignal]:
        # In-memory cache hit
        cached = self._ta_cache.get(ticker)
        if cached and time.time() < cached[0]:
            return cached[1]

        sig = self._compute_analyse(ticker, df)
        if sig:
            self._ta_cache[ticker] = (time.time() + self._TA_CACHE_TTL, sig)
        return sig

    def _compute_analyse(self, ticker: str, df: Optional[pd.DataFrame] = None) -> Optional[TASignal]:
        if SUVARN_API_URL:
            sig = self._analyse_via_api(ticker)
            if sig is not None:
                return sig
            print(f"[TAClient] {ticker} — API unavailable, using local fallback")
            return self._analyse_simple(ticker, df)

        if _USING_SIMPLE_TA:
            return self._analyse_simple(ticker, df)

        if df is None:
            df = fetch_ohlcv(ticker)
        if df is None or len(df) < 200:
            return None

        df        = df.copy()
        bar_idx   = len(df)
        df_slice  = df.iloc[-400:]

        # ── Regime (every 28 bars, full-history classifier) ───────────────────
        regime = self._regime_state.get(ticker)
        if regime is None or bar_idx >= self._regime_recalc.get(ticker, 0):
            regime = _classify_regime(df)
            self._regime_state[ticker]  = regime
            self._regime_recalc[ticker] = bar_idx + 28
            print(f"[TA] {ticker} regime={regime}")

        # ── Score ─────────────────────────────────────────────────────────────
        score     = _compute_score_for_ticker(df_slice, regime)
        threshold = _THRESHOLDS.get(regime, 3.0)

        if score >= threshold:
            action = "BUY"
        elif score <= 0.0:
            action = "SELL"
        else:
            action = "HOLD"

        conf = _confidence(score, threshold, action)

        # ── Per-masala breakdown ──────────────────────────────────────────────
        ms = _masala_scores(df_slice)
        print(f"[TA] {ticker} score={score:.4f} regime={regime} "
              f"mr={ms['meanrev']:.3f} tr={ms['trend']:.3f} "
              f"mom={ms['momentum']:.3f} wh={ms['whales']:.3f} → {action}")

        # ── Patterns + S/R ────────────────────────────────────────────────────
        patterns            = _detect_patterns(df)
        support, resistance = _support_resistance(df)

        closes = df_slice["close"]
        return TASignal(
            ticker           = ticker,
            score            = score,
            regime           = regime,
            regime_desc      = _REGIME_DESCRIPTIONS.get(regime, ""),
            threshold        = threshold,
            suggested_action = action,
            confidence       = conf,
            last_close       = float(closes.iloc[-1]),
            prev_close       = float(closes.iloc[-2]) if len(closes) >= 2 else None,
            masala_scores    = ms,
            patterns         = patterns,
            support          = support,
            resistance       = resistance,
        )

    def analyse_many(self, tickers: List[str], max_workers: int = 8) -> Dict[str, TASignal]:
        now = time.time()
        # Split into cached and needs-compute
        results: Dict[str, TASignal] = {}
        miss: List[str] = []
        for t in tickers:
            cached = self._ta_cache.get(t)
            if cached and now < cached[0]:
                results[t] = cached[1]
            else:
                miss.append(t)

        if not miss:
            return results

        fresh = self._compute_analyse_many(miss, max_workers)
        exp = now + self._TA_CACHE_TTL
        for t, sig in fresh.items():
            self._ta_cache[t] = (exp, sig)
        results.update(fresh)
        return results

    def _compute_analyse_many(self, tickers: List[str], max_workers: int = 8) -> Dict[str, TASignal]:
        if SUVARN_API_URL:
            res = self._analyse_many_via_api(tickers)
            if res:
                return res
            print(f"[TAClient] bulk — API unavailable, using local fallback for {len(tickers)} tickers")
            return self._analyse_many_simple(tickers)

        if _USING_SIMPLE_TA:
            return self._analyse_many_simple(tickers)

        df_map = fetch_all_ohlcv(tickers, max_workers=max_workers)

        signals = _generate_signals(
            tickers      = [t for t in tickers if t in df_map],
            df_dict      = df_map,
            regime_state = self._regime_state,
            next_recalc  = self._regime_recalc,
            lookback     = 400,
        )

        out: Dict[str, TASignal] = {}
        for sig in signals:
            t   = sig["ticker"]
            df  = df_map.get(t)
            if df is None:
                continue

            df_slice = df.iloc[-400:]
            ms       = _masala_scores(df_slice)
            patterns = _detect_patterns(df)
            support, resistance = _support_resistance(df)

            action = sig["suggested_action"].upper()

            print(f"[TA] {t} score={sig['score']:.4f} regime={sig['regime']} "
                  f"mr={ms['meanrev']:.3f} tr={ms['trend']:.3f} "
                  f"mom={ms['momentum']:.3f} wh={ms['whales']:.3f} → {action}")

            closes = df_slice["close"]
            out[t] = TASignal(
                ticker           = t,
                score            = sig["score"],
                regime           = sig.get("regime") or "RANGE",
                regime_desc      = _REGIME_DESCRIPTIONS.get(sig.get("regime") or "RANGE", ""),
                threshold        = sig["threshold"],
                suggested_action = action,
                confidence       = _confidence(sig["score"], sig["threshold"], action),
                last_close       = sig["last_close"],
                prev_close       = float(closes.iloc[-2]) if len(closes) >= 2 else None,
                masala_scores    = ms,
                patterns         = patterns,
                support          = support,
                resistance       = resistance,
            )

        return out
