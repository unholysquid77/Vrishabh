"""
SEBINewsIngestor — fetches SEBI regulatory circulars, orders, and enforcement actions
via NewsData.io + SEBI RSS feed.
"""

from __future__ import annotations
import xml.etree.ElementTree as ET
from typing import List

import requests

from global_graph.domains.base_raw_model import BaseRawModel
from global_graph.ingestors.newsdata_ingestor import NewsDataIngestor

# SEBI orders / press releases RSS
SEBI_RSS_FEEDS = [
    ("https://www.sebi.gov.in/sebirss.xml", "SEBI Official"),
]

SEBI_NEWS_QUERIES = [
    "SEBI circular regulation India market 2025",
    "SEBI enforcement order penalty insider trading",
    "SEBI IPO regulation listing India",
    "SEBI FPI FII regulation India",
    "SEBI mutual fund NFO India",
]


class SEBINewsIngestor(NewsDataIngestor):

    def __init__(self, api_key: str):
        super().__init__(api_key, domain="india_policy")

    def fetch(self, max_articles: int = 30) -> List[BaseRawModel]:
        results: List[BaseRawModel] = []
        seen: set = set()

        # 1. SEBI RSS feed
        for rss_url, source_label in SEBI_RSS_FEEDS:
            try:
                resp = requests.get(rss_url, timeout=15,
                                    headers={"User-Agent": "Mozilla/5.0 Vrishabh/1.0"})
                resp.raise_for_status()
                root = ET.fromstring(resp.content)
            except Exception as e:
                print(f"[SEBI RSS] {source_label} failed: {e}")
                continue

            for item in root.findall(".//item")[:10]:
                title   = (item.findtext("title") or "").strip()
                link    = (item.findtext("link")  or "").strip()
                pubdate = (item.findtext("pubDate") or "").strip()
                desc    = (item.findtext("description") or "").strip()[:500]

                if link in seen:
                    continue
                seen.add(link)

                results.append(BaseRawModel(
                    text       = f"[{source_label}] {title}\n{desc}",
                    source_url = link or rss_url,
                    domain     = "india_policy",
                    title      = title,
                    published  = pubdate,
                    tags       = ["SEBI", "regulation", "india", "securities"],
                ))

        # 2. NewsData queries
        for query in SEBI_NEWS_QUERIES:
            if len(results) >= max_articles:
                break
            articles = self.fetch_articles(
                query    = query,
                category = "politics,business",
                country  = "in",
                language = "en",
                max_pages = 1,
            )
            for a in articles:
                if a.source_url not in seen and a.text.strip():
                    seen.add(a.source_url)
                    results.append(a)

        return results[:max_articles]
