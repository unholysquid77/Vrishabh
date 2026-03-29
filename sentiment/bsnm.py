"""
BSNM Engine — Business Sentiment + News Market analysis.
Adapted from Suvarn's BusinessEngine.

Fetches articles from 3 sources → GPT-4o-mini sentiment →
weighted score per ticker.
No heavy transformer models — pure API-based.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Dict, List, Optional

from openai import OpenAI

from config import OPENAI_API_KEY, LLM_MODEL_FAST
from pipelines.news_pipeline import fetch_articles

SOURCE_WEIGHT  = {"marketaux": 1.0, "newsapi": 0.7, "newsdata": 0.5}
RECENCY_WEIGHT = {0: 1.0, 1: 0.8, 2: 0.5}   # days old → weight


class BSNMResult:
    def __init__(
        self,
        ticker: str,
        score: float,
        headline_summary: str,
        articles_found: int,
        top_headlines: List[str],
    ):
        self.ticker           = ticker
        self.score            = score
        self.headline_summary = headline_summary
        self.articles_found   = articles_found
        self.top_headlines    = top_headlines

    def to_dict(self) -> dict:
        return {
            "ticker":           self.ticker,
            "score":            round(self.score, 4),
            "headline_summary": self.headline_summary,
            "articles_found":   self.articles_found,
            "top_headlines":    self.top_headlines,
        }


class BSNMEngine:
    """
    Single-ticker business sentiment scoring via news APIs + GPT-4o-mini.
    """

    def __init__(self, openai_key: Optional[str] = None):
        key = openai_key or OPENAI_API_KEY
        self.client = OpenAI(api_key=key) if key else None

    def analyse(self, ticker: str) -> BSNMResult:
        articles = fetch_articles(ticker)

        if not articles:
            return BSNMResult(ticker, 0.0, "No news found.", 0, [])

        raw_score, weighted_score = self._score(ticker, articles)

        top_headlines = [a["title"] for a in articles[:5] if a.get("title")]

        return BSNMResult(
            ticker           = ticker,
            score            = weighted_score,
            headline_summary = self._summarise(ticker, articles),
            articles_found   = len(articles),
            top_headlines    = top_headlines,
        )

    def analyse_many(self, tickers: List[str]) -> Dict[str, BSNMResult]:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = {}
        with ThreadPoolExecutor(max_workers=5) as ex:
            futures = {ex.submit(self.analyse, t): t for t in tickers}
            for fut in as_completed(futures):
                ticker = futures[fut]
                results[ticker] = fut.result()
        return results

    # ──────────────────────────────────────────
    # SCORING
    # ──────────────────────────────────────────

    def _score(self, ticker: str, articles: List[dict]) -> tuple[float, float]:
        """Returns (raw_score, weighted_score)."""
        if not self.client:
            return 0.0, 0.0

        snippets = "\n".join(
            f"- [{a['source']}] {a['title']}"
            for a in articles[:12]
        )

        prompt = f"""You are a financial sentiment analyst covering Indian markets.

Rate the overall business/market sentiment for {ticker} based on these news headlines.
Return ONLY a JSON object: {{"score": <float -1.0 to 1.0>}}

-1.0 = very negative (profit warning, scandal, sector collapse)
 0.0 = neutral
+1.0 = very positive (earnings beat, contract win, upgrade)

Headlines:
{snippets}
"""

        try:
            resp = self.client.chat.completions.create(
                model=LLM_MODEL_FAST,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            raw = json.loads(resp.choices[0].message.content)
            raw_score = float(raw.get("score", 0.0))
        except Exception:
            raw_score = 0.0

        # Apply source + recency weights
        total_w = 0.0
        total_s = 0.0
        for a in articles:
            src = a.get("source", "newsdata")
            pub = a.get("published_at", "")
            try:
                days_old = (datetime.utcnow() - datetime.fromisoformat(pub[:10])).days
            except Exception:
                days_old = 2

            sw = SOURCE_WEIGHT.get(src, 0.5)
            rw = RECENCY_WEIGHT.get(min(days_old, 2), 0.5)
            w  = sw * rw

            total_s += raw_score * w
            total_w += w

        weighted = round(total_s / total_w, 4) if total_w > 0 else 0.0
        return raw_score, weighted

    def _summarise(self, ticker: str, articles: List[dict]) -> str:
        if not self.client or not articles:
            return ""

        snippets = "\n".join(
            f"- {a['title']}: {a.get('content', '')[:200]}"
            for a in articles[:8]
        )

        prompt = f"""Summarise the key business news about {ticker} in 2 concise sentences for a retail investor.
Focus on what matters for the stock price. Be specific.

Articles:
{snippets}"""

        try:
            resp = self.client.chat.completions.create(
                model=LLM_MODEL_FAST,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=150,
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            return ""
