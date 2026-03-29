"""
NewsDataIngestor — base class for NewsData.io-backed ingestors.
Handles pagination, dedup, and conversion to BaseRawModel.
"""

from __future__ import annotations
import hashlib
import json
import os
import time
from typing import List, Optional

import requests

from global_graph.domains.base_raw_model import BaseRawModel

NEWSDATA_BASE = "https://newsdata.io/api/1/news"
CACHE_DIR     = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                              "data", "global_cache")
CACHE_TTL_H   = 6   # hours


def _cache_path(key: str) -> str:
    h = hashlib.md5(key.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{h}.json")


def _load_cache(key: str) -> Optional[List[dict]]:
    path = _cache_path(key)
    if not os.path.exists(path):
        return None
    age_h = (time.time() - os.path.getmtime(path)) / 3600
    if age_h > CACHE_TTL_H:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_cache(key: str, data: List[dict]):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(_cache_path(key), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


class NewsDataIngestor:
    """
    Fetch articles from NewsData.io for a given query/category.
    Subclasses override `fetch_raw_articles` to customize query params.
    """

    def __init__(self, api_key: str, domain: str):
        self._api_key = api_key
        self._domain  = domain

    def fetch_articles(
        self,
        query:     str,
        category:  Optional[str] = None,
        country:   Optional[str] = None,
        language:  str           = "en",
        max_pages: int           = 2,
    ) -> List[BaseRawModel]:
        """Fetch articles and return as BaseRawModel list."""
        cache_key = f"{self._domain}:{query}:{category}:{country}:{language}"
        cached = _load_cache(cache_key)
        if cached is not None:
            return [self._to_raw(a) for a in cached]

        articles: List[dict] = []
        next_page = None

        for _ in range(max_pages):
            params: dict = {
                "apikey":   self._api_key,
                "q":        query,
                "language": language,
            }
            if category:
                params["category"] = category
            if country:
                params["country"] = country
            if next_page:
                params["page"] = next_page

            try:
                resp = requests.get(NEWSDATA_BASE, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                break

            results = data.get("results", [])
            articles.extend(results)
            next_page = data.get("nextPage")
            if not next_page:
                break

        _save_cache(cache_key, articles)
        return [self._to_raw(a) for a in articles]

    def _to_raw(self, article: dict) -> BaseRawModel:
        content = article.get("content") or article.get("description") or ""
        title   = article.get("title") or ""
        # Prepend title to content for richer extraction
        full_text = f"{title}\n\n{content}".strip()

        return BaseRawModel(
            text        = full_text,
            source_url  = article.get("link") or article.get("source_id", ""),
            domain      = self._domain,
            title       = title,
            published   = article.get("pubDate"),
            tags        = article.get("keywords") or [],
        )
