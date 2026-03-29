"""
IndianAPI.in — Indian Stock Market data client.

Endpoints used:
  GET /stock?name=TICKER         → live quote, technicals, financials
  GET /trending                  → top gainers / losers
  GET /NSE_most_active           → most traded NSE stocks
  GET /price_shockers            → big intraday movers
  GET /fetch_52_week_high_low_data → 52-week extremes
  GET /historical_data?stock_name=TICKER → OHLCV history

Requires INDIANAPI_KEY env var (set X-Api-Key header).
"""

from __future__ import annotations

import os
import time
from typing import Dict, List, Optional

import requests

INDIANAPI_BASE    = "https://api.indianapi.in"
_REQ_INTERVAL     = 1.1   # seconds between per-ticker calls (1 req/s limit)
_BUDGET_TOP_N     = 15    # top watchlist stocks to enrich with live prices
_BUDGET_BOTTOM_N  = 5     # bottom watchlist stocks to enrich with live prices


class IndianAPIClient:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("INDIANAPI_KEY", "")
        self._session = requests.Session()
        if self.api_key:
            self._session.headers.update({"X-Api-Key": self.api_key})

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def _get(self, path: str, params: dict = None) -> Optional[dict]:
        if not self.available:
            return None
        try:
            r = self._session.get(
                f"{INDIANAPI_BASE}{path}",
                params=params or {},
                timeout=12,
            )
            if r.status_code == 429:
                print(f"[IndianAPI] Rate limit hit on {path} — skipping")
                return None
            if r.status_code == 401:
                print("[IndianAPI] Invalid API key (401) — check INDIANAPI_KEY")
                return None
            r.raise_for_status()
            data = r.json()
            # API sometimes wraps errors in {"error": "..."}
            if isinstance(data, dict) and "error" in data and len(data) == 1:
                print(f"[IndianAPI] {path} API error: {data['error']}")
                return None
            return data
        except requests.exceptions.Timeout:
            print(f"[IndianAPI] Timeout on {path}")
            return None
        except requests.exceptions.ConnectionError as e:
            print(f"[IndianAPI] Connection error on {path}: {e}")
            return None
        except Exception as e:
            print(f"[IndianAPI] {path} error: {e}")
            return None

    # ──────────────────────────────────────────────
    # RAW ENDPOINTS
    # ──────────────────────────────────────────────

    def get_stock(self, name: str) -> Optional[dict]:
        """Full stock profile — prices, technicals, financials, news."""
        return self._get("/stock", {"name": name})

    def get_trending(self) -> Optional[dict]:
        """Top gainers and losers across markets."""
        return self._get("/trending")

    def get_nse_most_active(self) -> Optional[list]:
        return self._get("/NSE_most_active")

    def get_price_shockers(self) -> Optional[list]:
        return self._get("/price_shockers")

    def get_52_week(self) -> Optional[dict]:
        return self._get("/fetch_52_week_high_low_data")

    def get_historical(self, stock_name: str, period: str = "1yr") -> Optional[dict]:
        return self._get("/historical_data", {"stock_name": stock_name, "period": period})

    # ──────────────────────────────────────────────
    # NORMALISED HELPERS
    # ──────────────────────────────────────────────

    def get_live_price(self, ticker: str) -> Optional[dict]:
        """
        Returns {ticker, price, prev_close, pct_change, source} or None.
        Tries NSE data first, falls back to BSE.
        Counts as 1 request — use sparingly.
        """
        data = self.get_stock(ticker)
        if not data:
            return None
        try:
            # Unwrap list responses
            if isinstance(data, list):
                data = data[0] if data else None
            if not isinstance(data, dict):
                return None

            # indianapi returns nse_data / bse_data sub-dicts
            nse = data.get("nse_data") or data.get("bse_data") or {}
            if not isinstance(nse, dict):
                nse = {}

            price = _coerce_float(
                nse.get("close") or nse.get("price") or
                nse.get("lastPrice") or nse.get("current_price") or
                data.get("current_price")
            )
            prev = _coerce_float(
                nse.get("prev_close") or nse.get("previousClose") or
                nse.get("previous_close") or data.get("prev_close")
            )
            if price is None:
                return None

            pct = round((price - prev) / prev * 100, 2) if prev else None
            return {
                "ticker":     ticker,
                "price":      price,
                "prev_close": prev,
                "pct_change": pct,
                "source":     "indianapi",
            }
        except Exception as e:
            print(f"[IndianAPI] get_live_price({ticker}) parse error: {e}")
            return None

    def get_live_prices_batch(
        self,
        tickers_sorted_by_pct: List[str],
        top_n: int = _BUDGET_TOP_N,
        bottom_n: int = _BUDGET_BOTTOM_N,
    ) -> Dict[str, dict]:
        """
        Fetch live prices for the top N + bottom N tickers from a list
        pre-sorted by pct_change descending. Throttles at 1 req/s.

        With 500 req/month budget: call this at most ~25×/month (20 tickers each).
        Returns {ticker: live_price_dict}.
        """
        n = len(tickers_sorted_by_pct)
        top    = tickers_sorted_by_pct[:top_n]
        bottom = tickers_sorted_by_pct[max(0, n - bottom_n):]
        # Dedup while preserving order
        seen: set = set()
        targets   = []
        for t in top + bottom:
            if t not in seen:
                seen.add(t)
                targets.append(t)

        results: Dict[str, dict] = {}
        for ticker in targets:
            price_info = self.get_live_price(ticker)
            if price_info:
                results[ticker] = price_info
            time.sleep(_REQ_INTERVAL)   # respect 1 req/s limit

        return results

    def get_movers(self, topk: int = 5) -> Dict[str, List[dict]]:
        """
        Returns {"gainers": [...], "losers": [...]} from /trending.
        Costs 1 request. Falls back to empty lists if unavailable.
        """
        data = self.get_trending()
        if not data:
            return {"gainers": [], "losers": []}
        if not isinstance(data, dict):
            print(f"[IndianAPI] /trending returned unexpected type {type(data)}")
            return {"gainers": [], "losers": []}
        try:
            gainers_raw = data.get("gainers") or data.get("top_gainers") or []
            losers_raw  = data.get("losers")  or data.get("top_losers")  or []
            if not isinstance(gainers_raw, list):
                gainers_raw = []
            if not isinstance(losers_raw, list):
                losers_raw = []

            def _norm(items: list) -> List[dict]:
                out = []
                for item in items[:topk]:
                    if not isinstance(item, dict):
                        continue
                    ticker = _clean_ticker(
                        item.get("ticker") or item.get("symbol") or
                        item.get("nse_code") or item.get("bse_code") or ""
                    )
                    price = _coerce_float(
                        item.get("price") or item.get("last_price") or item.get("close")
                    )
                    pct = _coerce_float(
                        item.get("percent_change") or item.get("pct_change") or
                        item.get("change_percent") or item.get("percentChange")
                    )
                    if ticker and price is not None:
                        out.append({
                            "ticker":     ticker,
                            "price":      price,
                            "pct_change": pct or 0.0,
                            "source":     "indianapi",
                        })
                return out

            return {"gainers": _norm(gainers_raw), "losers": _norm(losers_raw)}
        except Exception as e:
            print(f"[IndianAPI] get_movers parse error: {e}")
            return {"gainers": [], "losers": []}

    def get_52_week_extremes(self) -> Dict[str, List[dict]]:
        """Returns {"highs": [...], "lows": [...]} of stocks at 52-week extremes."""
        data = self.get_52_week()
        if not data:
            return {"highs": [], "lows": []}
        try:
            highs_raw = data.get("bse_52_week_high") or data.get("nse_52_week_high") or []
            lows_raw  = data.get("bse_52_week_low")  or data.get("nse_52_week_low")  or []

            def _norm(items):
                out = []
                for item in items[:20]:
                    if not isinstance(item, dict):
                        continue
                    ticker = _clean_ticker(
                        item.get("ticker") or item.get("symbol") or item.get("name") or ""
                    )
                    price = _coerce_float(item.get("price") or item.get("close"))
                    if ticker:
                        out.append({"ticker": ticker, "price": price})
                return out

            return {"highs": _norm(highs_raw), "lows": _norm(lows_raw)}
        except Exception:
            return {"highs": [], "lows": []}


# ──────────────────────────────────────────────
# UTILS
# ──────────────────────────────────────────────

def _coerce_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _clean_ticker(raw) -> str:
    if not raw or not isinstance(raw, str):
        return ""
    return raw.upper().replace(".NS", "").replace(".BO", "").strip()
