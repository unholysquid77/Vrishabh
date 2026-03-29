"""
suvarn_client/bsnm_client.py — Business Sentiment & News Market facade.

Suvarn's native BusinessEngine.py has been updated (v2.0) to use a single
GPT-4o-mini call per ticker instead of heavy BART/FinBERT transformer models.
The Suvarn API exposes this via GET /sentiment/{ticker}.

Dev mode  (SUVARN_API_URL unset): delegates to Vrishabh's local GPT-4o-mini BSNMEngine.
Prod mode (SUVARN_API_URL set):   calls GET {SUVARN_API_URL}/sentiment/{ticker}.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import requests

from ._loader import DEV_MODE, SUVARN_API_URL

# Re-export BSNMResult so callers only need to import from suvarn_client
from sentiment.bsnm import BSNMEngine as _BSNMEngine, BSNMResult  # noqa: F401


class SuvarnBSNMClient:
    """
    Facade over Suvarn's BSNM pipeline.

    Dev mode  → delegates to Vrishabh's GPT-4o-mini BSNMEngine.
    Prod mode → calls GET {SUVARN_API_URL}/sentiment/{ticker}.
    """

    def __init__(self, openai_key: Optional[str] = None):
        self._engine   = _BSNMEngine(openai_key=openai_key)
        self._api_key  = openai_key

    # ── Prod-mode HTTP helpers ─────────────────────────────────────────────────

    def _result_from_api(self, ticker: str) -> Optional[BSNMResult]:
        """
        Call GET {SUVARN_API_URL}/sentiment/{ticker} and parse into BSNMResult.
        Returns None on any error (caller falls back to dev engine if needed).
        """
        url = f"{SUVARN_API_URL.rstrip('/')}/sentiment/{ticker}"
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            d = resp.json()
            if d.get("error"):
                print(f"[SuvarnAPI/BSNM] {ticker}: {d['error']}")
                return None
            score   = float(d.get("score", 0.0))
            summary = d.get("headline_summary", "")
            found   = int(d.get("articles_found", 0))
            heads   = d.get("top_headlines", [])
            print(f"[SuvarnAPI/BSNM] {ticker} score={score:.3f} articles={found}")
            return BSNMResult(
                ticker           = ticker,
                score            = score,
                headline_summary = summary,
                articles_found   = found,
                top_headlines    = heads,
            )
        except Exception as e:
            print(f"[SuvarnAPI/BSNM] {ticker} request failed: {e}")
            return None

    # ── Main interface ─────────────────────────────────────────────────────────

    def analyse(self, ticker: str) -> BSNMResult:
        if not DEV_MODE:
            result = self._result_from_api(ticker)
            if result is not None:
                return result
            # Fallback to dev engine if API call fails
            print(f"[SuvarnBSNMClient] Falling back to local engine for {ticker}")

        return self._engine.analyse(ticker)

    def analyse_many(self, tickers: List[str]) -> Dict[str, BSNMResult]:
        if not DEV_MODE:
            results: Dict[str, BSNMResult] = {}
            for ticker in tickers:
                r = self._result_from_api(ticker)
                if r is not None:
                    results[ticker] = r
                else:
                    # Fallback per-ticker
                    try:
                        results[ticker] = self._engine.analyse(ticker)
                    except Exception as e:
                        print(f"[SuvarnBSNMClient] fallback failed for {ticker}: {e}")
            return results

        return self._engine.analyse_many(tickers)
