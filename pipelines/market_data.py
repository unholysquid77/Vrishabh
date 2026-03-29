"""
Market Data Pipeline
Fetches OHLCV from yfinance → populates Company entities and
stores price data in a local cache for the TA engine.
"""

import os
import json
import threading
import time
import datetime as _dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

# yfinance is NOT thread-safe: concurrent yf.download() calls can return
# each other's data, corrupting the parquet cache. Serialize all downloads.
_YF_DOWNLOAD_LOCK = threading.Lock()

from config import NIFTY_500_TICKERS, TA_LOOKBACK_BARS, to_yf_ticker
from graph import FinanceGraph, GraphRepository
from graph.entities import make_company, make_macro_indicator, SourceInfo, EntityType
from graph.relations import make_relation, RelationType


# ──────────────────────────────────────────────
# PRICE CACHE
# Files: data/prices/{TICKER}.parquet
# ──────────────────────────────────────────────

PRICE_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "prices")
os.makedirs(PRICE_CACHE_DIR, exist_ok=True)


def _cache_path(ticker: str) -> str:
    return os.path.join(PRICE_CACHE_DIR, f"{ticker}.parquet")


def _market_is_open() -> bool:
    """True if NSE is likely open (Mon–Fri, 09:00–16:00 IST)."""
    IST = _dt.timedelta(hours=5, minutes=30)
    now = _dt.datetime.utcnow() + IST
    return now.weekday() < 5 and 9 <= now.hour < 16


def _cache_is_fresh(ticker: str, max_age_hours: float = 6.0) -> bool:
    path = _cache_path(ticker)
    if not os.path.exists(path):
        return False
    age = time.time() - os.path.getmtime(path)
    # Extend TTL when markets are closed to avoid unnecessary re-downloads
    if not _market_is_open():
        max_age_hours = max(max_age_hours, 20.0)
    return age < max_age_hours * 3600


def fetch_ohlcv(ticker: str, bars: int = TA_LOOKBACK_BARS, force: bool = False) -> Optional[pd.DataFrame]:
    """
    Fetch daily OHLCV for a ticker. Returns DataFrame with lowercase columns:
    open, high, low, close, volume — indexed by datetime.
    Uses parquet cache; refreshes if stale OR if the cached file has fewer rows
    than the requested `bars` (so a 3-year backtest call won't silently return
    the 300-bar TA cache).
    """
    yf_ticker = to_yf_ticker(ticker)
    path      = _cache_path(ticker)

    if not force and _cache_is_fresh(ticker):
        try:
            df = pd.read_parquet(path).sort_index()
            if len(df) >= bars:          # cache has enough history
                return df.tail(bars)
            # cache is too short for this request → fall through to re-download
        except Exception:
            pass

    try:
        # Use named yfinance periods where possible (more reliable than "800d" etc.)
        if bars <= 300:
            period = "1y"
        elif bars <= 500:
            period = "2y"
        else:
            period = "3y"              # covers up to ~756 trading days
        with _YF_DOWNLOAD_LOCK:        # serialize: yfinance is not thread-safe
            df = yf.download(yf_ticker, period=period, auto_adjust=True, progress=False)

        if df.empty:
            return None

        # Flatten MultiIndex if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.rename(columns={c: c.lower() for c in df.columns})
        cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        if "close" not in cols:
            return None
        df = df[cols].copy()
        if "volume" not in df.columns:
            df["volume"] = 0  # indices/forex may lack volume
        df = df[["open", "high", "low", "close", "volume"]]
        df.index = pd.to_datetime(df.index)
        df = df.sort_index().dropna()

        df.to_parquet(path)
        return df.tail(bars)

    except Exception as e:
        print(f"[MarketData] Failed to fetch {ticker}: {e}")
        # Last resort: return stale cache so the app doesn't break when offline
        if os.path.exists(path):
            try:
                df = pd.read_parquet(path).sort_index()
                if len(df) > 0:
                    print(f"[MarketData] Using stale cache for {ticker}")
                    return df.tail(bars)
            except Exception:
                pass
        return None


def fetch_all_ohlcv(
    tickers: List[str],
    bars: int = TA_LOOKBACK_BARS,
    max_workers: int = 10,
    force: bool = False,
) -> Dict[str, pd.DataFrame]:
    """Concurrent fetch for all tickers. Returns {ticker: df}."""
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_ohlcv, t, bars, force): t for t in tickers}
        for fut in as_completed(futures):
            ticker = futures[fut]
            df = fut.result()
            if df is not None and not df.empty:
                results[ticker] = df
    return results


# ──────────────────────────────────────────────
# NIFTY / INDEX METADATA (from yfinance)
# ──────────────────────────────────────────────

INDEX_TICKERS = {
    "Nifty50":      "^NSEI",
    "Nifty_Bank":   "^NSEBANK",
    "Nifty_IT":     "^CNXIT",
    "Nifty_Pharma": "^CNXPHARMA",
    "Sensex":       "^BSESN",
    "USD_INR":      "INR=X",
}


def fetch_index_values() -> Dict[str, float]:
    """Returns {name: latest_close} for key indices."""
    values = {}
    for name, sym in INDEX_TICKERS.items():
        try:
            info = yf.download(sym, period="2d", auto_adjust=True, progress=False)
            if not info.empty:
                if isinstance(info.columns, pd.MultiIndex):
                    info.columns = info.columns.get_level_values(0)
                values[name] = float(info["Close"].iloc[-1])
        except Exception:
            pass
    return values


# ──────────────────────────────────────────────
# COMPANY INFO FROM yfinance
# ──────────────────────────────────────────────

def fetch_company_info(ticker: str) -> dict:
    """Returns basic info dict from yfinance Ticker.info."""
    try:
        info = yf.Ticker(to_yf_ticker(ticker)).info
        return {
            "name":        info.get("longName") or info.get("shortName") or ticker,
            "sector":      info.get("sector"),
            "industry":    info.get("industry"),
            "market_cap":  info.get("marketCap"),   # in base currency
            "description": info.get("longBusinessSummary"),
            "exchange":    info.get("exchange", "NSE"),
        }
    except Exception:
        return {"name": ticker, "sector": None, "industry": None, "market_cap": None, "description": None, "exchange": "NSE"}


# ──────────────────────────────────────────────
# PIPELINE CLASS
# ──────────────────────────────────────────────

class MarketDataPipeline:
    """
    Populates the finance graph with Company entities and
    MacroIndicator entities from yfinance data.
    """

    def __init__(self, repo: GraphRepository):
        self.repo  = repo
        self.graph = repo.graph

    # ─────────────────────────────────────
    # ENSURE SECTOR NODE EXISTS
    # ─────────────────────────────────────

    def _ensure_sector(self, sector_name: str) -> str:
        """Returns node_id of the sector entity, creating it if absent."""
        from graph.entities import make_sector
        existing = [
            n for n in self.graph.get_by_type(EntityType.SECTOR)
            if n.canonical_name.lower() == sector_name.lower()
        ]
        if existing:
            return existing[0].id

        node = make_sector(sector_name)
        return self.graph.add_node(node)

    # ─────────────────────────────────────
    # UPSERT A COMPANY
    # ─────────────────────────────────────

    def upsert_company(self, ticker: str, info: Optional[dict] = None) -> str:
        """
        Creates or updates a Company node. Returns node_id.
        Links to sector if available.
        """
        if info is None:
            info = fetch_company_info(ticker)

        existing = self.graph.get_company_node(ticker)

        # market_cap from yfinance is in INR base units — convert to crores
        mc_raw   = info.get("market_cap")
        mc_cr    = round(mc_raw / 1e7, 2) if mc_raw else None

        node = make_company(
            ticker      = ticker,
            name        = info["name"],
            sector      = info.get("sector"),
            industry    = info.get("industry"),
            exchange    = info.get("exchange", "NSE"),
            market_cap  = mc_cr,
            description = info.get("description"),
            aliases     = [ticker],
            sources     = [SourceInfo(source_name="yfinance")],
        )

        if existing:
            node.id = existing.id
            self.graph.update_node(existing.id, node)
            company_id = existing.id
        else:
            company_id = self.graph.add_node(node)

        # Link to sector
        sector_name = info.get("sector")
        if sector_name:
            sector_id = self._ensure_sector(sector_name)
            try:
                rel = make_relation(RelationType.IN_SECTOR, company_id, sector_id)
                self.graph.add_relation(rel)
            except KeyError:
                pass

        return company_id

    # ─────────────────────────────────────
    # SYNC MACRO INDICATORS
    # ─────────────────────────────────────

    def sync_macro_indicators(self):
        values = fetch_index_values()
        for name, value in values.items():
            existing = [
                n for n in self.graph.get_by_type(EntityType.MACRO_INDICATOR)
                if n.canonical_name == name
            ]
            node = make_macro_indicator(
                name    = name,
                value   = value,
                unit    = "points" if "USD" not in name else "INR",
                as_of   = datetime.utcnow(),
                sources = [SourceInfo(source_name="yfinance")],
            )
            if existing:
                node.id = existing[0].id
                self.graph.update_node(existing[0].id, node)
            else:
                self.graph.add_node(node)

    # ─────────────────────────────────────
    # FULL SYNC
    # ─────────────────────────────────────

    def run(self, tickers: Optional[List[str]] = None, fetch_info: bool = True):
        """
        Populates/refreshes company nodes for all tickers.
        Also syncs macro indicators.
        """
        tickers = tickers or NIFTY_500_TICKERS
        print(f"[MarketData] Syncing {len(tickers)} companies...")

        if fetch_info:
            with ThreadPoolExecutor(max_workers=8) as ex:
                futures = {ex.submit(fetch_company_info, t): t for t in tickers}
                for fut in as_completed(futures):
                    ticker = futures[fut]
                    info   = fut.result()
                    self.upsert_company(ticker, info)
                    print(f"  [+] {ticker} — {info['name']}")
        else:
            for t in tickers:
                self.upsert_company(t)

        self.sync_macro_indicators()
        print("[MarketData] Done. Saving graph...")
        self.repo.save()
        print("[MarketData] Graph saved.")
