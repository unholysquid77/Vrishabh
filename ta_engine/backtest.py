"""
Backtesting engine — simulates the simple MACD+Supertrend+ADX+BB strategy
on historical OHLCV and returns an equity curve + performance metrics.

Used by GET /backtest/{ticker} regardless of which live TA engine is active.
Design goals:
  - No look-ahead bias (signal at bar i → trade opens at bar i+1's open)
  - Long-only (Indian retail context)
  - Includes 0.1% commission per trade (each leg)
  - Returns equity normalized to 100 at start
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd
from typing import Dict, List

from ta_engine.simple_ta import score_series

COMMISSION = 0.001   # 0.1% per leg

# Backtest uses looser thresholds than live TA (live is 1.5/-0.0).
# Looser thresholds produce more signal crossings over 3 years,
# which is what a backtest needs to measure strategy quality.
BUY_THRESHOLD  =  0.40
SELL_THRESHOLD = -0.40


def run(df: pd.DataFrame, ticker: str = "") -> dict:
    """
    Backtest the simple TA strategy on df (lowercase OHLCV columns).

    Returns:
        equity_curve: [{time, value, benchmark}]  (100-normalized, ~200 sampled points)
        trades:       last 20 trades [{entry_date, exit_date, return_pct, entry, exit}]
        total_return_pct, cagr_pct, win_rate, max_drawdown_pct,
        sharpe, num_trades, benchmark_return_pct
    """
    if len(df) < 80:
        return {"error": "insufficient data for backtest"}

    close  = df["close"].values.astype(float)
    open_  = df["open"].values.astype(float) if "open" in df.columns else close
    dates  = [str(d)[:10] for d in df.index]
    n      = len(close)

    # ── Pre-compute indicator scores for all bars ─────────────────────────────
    try:
        scores = score_series(df).values.astype(float)
    except Exception:
        return {"error": "indicator computation failed"}

    # NaN for the first ~35 bars (MACD warmup) — treat as HOLD
    scores = np.nan_to_num(scores, nan=0.0)

    # Mask warmup bars so spurious Supertrend initialization (+1 before ATR is
    # ready) doesn't produce a fake BUY signal on bar 1.  All indicators are
    # warm by bar 40 (MACD needs 34 bars, Supertrend/ADX need 14-28 bars).
    WARMUP = 40
    scores[:WARMUP] = 0.0

    # ── Simulation ────────────────────────────────────────────────────────────
    # Signal at bar i → entry at bar i+1 (open price) → no look-ahead
    cash        = 100.0      # normalised starting capital (equity starts at 100)
    shares      = 0.0
    entry_price = 0.0
    entry_date  = ""
    equity      = np.full(n, 100.0)
    trades: List[dict] = []

    for i in range(n):
        price_now = float(close[i])

        # Mark-to-market equity
        equity[i] = cash + shares * price_now

        if i == n - 1:
            break

        # Signal on this bar → execute on next bar's open
        sig   = scores[i]
        entry = float(open_[i + 1]) if i + 1 < n else price_now

        if shares == 0.0 and sig >= BUY_THRESHOLD:
            # Enter long at next bar open
            shares      = (cash * (1 - COMMISSION)) / entry
            entry_price = entry
            entry_date  = dates[i + 1] if i + 1 < n else dates[i]
            cash        = 0.0

        elif shares > 0.0 and sig <= SELL_THRESHOLD:
            # Exit long at next bar open
            proceeds = shares * entry * (1 - COMMISSION)
            ret_pct  = (entry - entry_price) / entry_price * 100 if entry_price > 0 else 0.0
            trades.append({
                "entry_date": entry_date,
                "exit_date":  dates[i + 1] if i + 1 < n else dates[i],
                "return_pct": round(ret_pct, 2),
                "entry":      round(entry_price, 2),
                "exit":       round(entry, 2),
            })
            cash   = proceeds
            shares = 0.0

    # Close open position at last close
    if shares > 0.0:
        last_price = float(close[-1])
        proceeds   = shares * last_price * (1 - COMMISSION)
        ret_pct    = (last_price - entry_price) / entry_price * 100 if entry_price > 0 else 0.0
        trades.append({
            "entry_date": entry_date,
            "exit_date":  dates[-1],
            "return_pct": round(ret_pct, 2),
            "entry":      round(entry_price, 2),
            "exit":       round(last_price, 2),
        })
        equity[-1] = proceeds

    # ── Benchmark: buy-and-hold ───────────────────────────────────────────────
    bh_equity = close / close[0] * 100.0

    # ── Sample to ~200 points for chart ──────────────────────────────────────
    sample_n = min(n, 200)
    idx      = np.linspace(0, n - 1, sample_n, dtype=int)
    equity_curve = [
        {
            "time":      dates[i],
            "value":     round(float(equity[i]), 2),
            "benchmark": round(float(bh_equity[i]), 2),
        }
        for i in idx
    ]

    # ── Metrics ───────────────────────────────────────────────────────────────
    final_val    = float(equity[-1])
    total_return = final_val - 100.0
    bh_return    = float(bh_equity[-1]) - 100.0

    n_years = n / 252.0
    cagr = ((final_val / 100.0) ** (1.0 / n_years) - 1.0) * 100.0 if n_years > 0 and final_val > 0 else 0.0

    # Max drawdown
    peak   = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    # Win rate
    num_trades = len(trades)
    win_rate   = (sum(1 for t in trades if t["return_pct"] > 0) / num_trades * 100) if num_trades else 0.0

    # Sharpe (annualised, daily returns)
    daily_rets = np.diff(equity) / equity[:-1]
    sharpe     = 0.0
    if len(daily_rets) > 1 and daily_rets.std() > 0:
        sharpe = float(daily_rets.mean() / daily_rets.std() * math.sqrt(252))

    return {
        "ticker":               ticker.upper().replace(".NS", ""),
        "equity_curve":         equity_curve,
        "trades":               trades[-20:],
        "total_return_pct":     round(total_return, 2),
        "cagr_pct":             round(cagr, 2),
        "win_rate":             round(win_rate, 1),
        "max_drawdown_pct":     round(max_dd, 2),
        "sharpe":               round(sharpe, 2),
        "num_trades":           num_trades,
        "benchmark_return_pct": round(bh_return, 2),
    }
