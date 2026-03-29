"""
News Pipeline
Fetches articles from MarketAux / NewsAPI / NewsData →
extracts company mentions + sentiment via GPT-4o-mini →
creates NewsItem and Event entities in the graph.
"""

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests
from openai import OpenAI

from config import (
    MARKETAUX_API_KEY, NEWSAPI_KEY, NEWSDATA_API_KEY, OPENAI_API_KEY,
    LLM_MODEL_FAST, NEWS_CACHE_TTL_HOURS, NEWS_MAX_ARTICLES,
)
from graph import GraphRepository
from graph.entities import make_news_item, make_event, SourceInfo, EntityType
from graph.relations import make_relation, RelationType


# ──────────────────────────────────────────────
# CACHE
# ──────────────────────────────────────────────

NEWS_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "news_cache")
os.makedirs(NEWS_CACHE_DIR, exist_ok=True)


def _cache_path(ticker: str) -> str:
    date = datetime.utcnow().strftime("%Y-%m-%d")
    return os.path.join(NEWS_CACHE_DIR, f"{ticker}_{date}.json")


def _load_cache(ticker: str) -> Optional[List[dict]]:
    path = _cache_path(ticker)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    ts  = datetime.fromisoformat(data["timestamp"])
    age = (datetime.utcnow() - ts).total_seconds() / 3600
    if age > NEWS_CACHE_TTL_HOURS:
        return None
    return data["articles"]


def _save_cache(ticker: str, articles: List[dict]):
    path = _cache_path(ticker)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"timestamp": datetime.utcnow().isoformat(), "articles": articles}, f)


# ──────────────────────────────────────────────
# TEXT CLEANING
# ──────────────────────────────────────────────

def _clean(text: Optional[str]) -> str:
    if not text:
        return ""
    text = re.sub(r"\[\+\d+\s*chars?\]", "", text)
    text = re.sub(r"\.{3,}", ".", text)
    for garbage in ["Live Events", "Click here", "Subscribe to", "ET Prime",
                    "Advertisement", "Expert Views", "Trending Now", "Market Wrap"]:
        text = text.replace(garbage, "")
    return text.strip()


# ──────────────────────────────────────────────
# FETCHERS
# ──────────────────────────────────────────────

def _fetch_marketaux(ticker: str) -> List[dict]:
    if not MARKETAUX_API_KEY:
        return []
    url = (
        f"https://api.marketaux.com/v1/news/all?"
        f"filter_entities=true&symbols={ticker}"
        f"&language=en&countries=in&api_token={MARKETAUX_API_KEY}"
    )
    try:
        res = requests.get(url, timeout=10).json()
        return [
            {
                "source":      "marketaux",
                "title":       a.get("title", ""),
                "content":     _clean(a.get("snippet", "")),
                "url":         a.get("url", ""),
                "published_at": a.get("published_at", ""),
            }
            for a in res.get("data", [])[:NEWS_MAX_ARTICLES]
        ]
    except Exception:
        return []


def _fetch_newsapi(ticker: str) -> List[dict]:
    if not NEWSAPI_KEY:
        return []
    url = (
        f"https://newsapi.org/v2/everything?"
        f"q={ticker}+India+stock&language=en&sortBy=publishedAt&apiKey={NEWSAPI_KEY}"
    )
    try:
        res = requests.get(url, timeout=10).json()
        return [
            {
                "source":      "newsapi",
                "title":       a.get("title", ""),
                "content":     _clean(a.get("content", "")),
                "url":         a.get("url", ""),
                "published_at": a.get("publishedAt", ""),
            }
            for a in res.get("articles", [])[:NEWS_MAX_ARTICLES]
        ]
    except Exception:
        return []


def _fetch_newsdata(ticker: str) -> List[dict]:
    if not NEWSDATA_API_KEY:
        return []
    url = (
        f"https://newsdata.io/api/1/latest?"
        f"apikey={NEWSDATA_API_KEY}&q={ticker}+India+business&country=in&category=business"
    )
    try:
        res = requests.get(url, timeout=10).json()
        return [
            {
                "source":      "newsdata",
                "title":       a.get("title", ""),
                "content":     _clean(a.get("content", "")),
                "url":         a.get("link", ""),
                "published_at": a.get("pubDate", ""),
            }
            for a in res.get("results", [])[:NEWS_MAX_ARTICLES]
        ]
    except Exception:
        return []


SOURCE_WEIGHT = {"marketaux": 1.0, "newsapi": 0.7, "newsdata": 0.5}


def fetch_articles(ticker: str) -> List[dict]:
    cached = _load_cache(ticker)
    if cached is not None:
        return cached

    articles = []
    articles += _fetch_marketaux(ticker)
    articles += _fetch_newsapi(ticker)
    articles += _fetch_newsdata(ticker)

    # Deduplicate by title
    seen, deduped = set(), []
    for a in articles:
        key = a["title"].strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(a)

    _save_cache(ticker, deduped)
    return deduped


# ──────────────────────────────────────────────
# LLM ANALYSIS
# ──────────────────────────────────────────────

def _analyse_articles(ticker: str, articles: List[dict], client: OpenAI) -> dict:
    """
    GPT-4o-mini analyses all articles for a ticker and returns:
    - sentiment_score (-1 to +1)
    - key_events: list of {event_type, title, description, magnitude}
    - summary: 2-3 sentence summary
    """
    if not articles:
        return {"sentiment_score": 0.0, "key_events": [], "summary": "No news found."}

    snippets = "\n".join(
        f"[{a['source']}] {a['title']} — {a['content'][:300]}"
        for a in articles[:12]
    )

    prompt = f"""You are a financial news analyst for Indian markets.

Analyse the following news articles about {ticker} and return a JSON object with:
- "sentiment_score": float from -1.0 (very negative) to +1.0 (very positive)
- "key_events": list of objects, each with:
    - "event_type": one of ["earnings_beat", "earnings_miss", "management_change", "M&A", "regulatory", "insider_trade", "partnership", "product_launch", "debt_upgrade", "debt_downgrade", "other"]
    - "title": short event title
    - "description": 1 sentence
    - "magnitude": float 0-1 (importance)
- "summary": 2-3 sentence overall summary for {ticker}

ONLY output valid JSON. No markdown.

Articles:
{snippets}
"""

    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL_FAST,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        print(f"[News] LLM analysis failed for {ticker}: {e}")
        return {"sentiment_score": 0.0, "key_events": [], "summary": "Analysis failed."}


# ──────────────────────────────────────────────
# PIPELINE CLASS
# ──────────────────────────────────────────────

class NewsPipeline:
    """
    Fetches news for a list of tickers → analyses with LLM →
    creates NewsItem + Event entities in the graph.
    """

    def __init__(self, repo: GraphRepository):
        self.repo   = repo
        self.graph  = repo.graph
        self.client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

    def run(self, tickers: List[str], max_workers: int = 5) -> Dict[str, float]:
        """
        Runs the full pipeline for given tickers.
        Returns {ticker: sentiment_score} map.
        """
        sentiments: Dict[str, float] = {}

        def _process(ticker):
            articles = fetch_articles(ticker)
            if self.client:
                analysis = _analyse_articles(ticker, articles, self.client)
            else:
                analysis = {"sentiment_score": 0.0, "key_events": [], "summary": "No LLM available."}

            score  = float(analysis.get("sentiment_score", 0.0))
            events = analysis.get("key_events", [])
            summary = analysis.get("summary", "")

            company_node = self.graph.get_company_node(ticker)

            # Ingest NewsItems
            for a in articles[:8]:
                try:
                    pub = datetime.fromisoformat(a["published_at"].replace("Z", "+00:00")) if a.get("published_at") else None
                except Exception:
                    pub = None

                news_node = make_news_item(
                    headline          = a["title"][:200],
                    source_name       = a["source"],
                    url               = a.get("url"),
                    published_at      = pub,
                    summary           = a["content"][:500] if a.get("content") else None,
                    sentiment_score   = score,
                    tickers_mentioned = [ticker],
                    sources           = [SourceInfo(source_name=a["source"], source_url=a.get("url"))],
                )
                nid = self.graph.add_node(news_node)

                if company_node:
                    try:
                        rel = make_relation(
                            RelationType.MENTIONED_IN,
                            company_node.id,
                            nid,
                            weight     = SOURCE_WEIGHT.get(a["source"], 0.5),
                            confidence = abs(score),
                        )
                        self.graph.add_relation(rel)
                    except KeyError:
                        pass

            # Ingest Events
            for ev in events:
                if not ev.get("title"):
                    continue
                event_node = make_event(
                    company_ticker = ticker,
                    event_type     = ev.get("event_type", "other"),
                    title          = ev["title"],
                    description    = ev.get("description"),
                    event_date     = datetime.utcnow(),
                    magnitude      = float(ev.get("magnitude", 0.5)),
                    sources        = [SourceInfo(source_name="news_pipeline")],
                )
                eid = self.graph.add_node(event_node)

                if company_node:
                    try:
                        rel = make_relation(RelationType.HAD_EVENT, company_node.id, eid)
                        self.graph.add_relation(rel)
                    except KeyError:
                        pass

            return ticker, score

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_process, t): t for t in tickers}
            for fut in as_completed(futures):
                ticker, score = fut.result()
                sentiments[ticker] = score
                print(f"  [News] {ticker}: sentiment={score:+.3f}")

        self.repo.save()
        return sentiments
