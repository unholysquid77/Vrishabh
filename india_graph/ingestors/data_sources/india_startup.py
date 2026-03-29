"""
IndiaStartupIngestor — Indian startup ecosystem: funding rounds, unicorns,
M&A, and VC activity. Uses NewsData.io with India startup keywords.
"""

from __future__ import annotations
from typing import List

from global_graph.domains.base_raw_model import BaseRawModel
from global_graph.ingestors.newsdata_ingestor import NewsDataIngestor

STARTUP_QUERIES = [
    "India startup funding Series A B C D 2025",
    "India unicorn valuation billion startup",
    "India VC venture capital investment fund raise",
    "Zomato Swiggy Meesho PhonePe Ola startup",
    "India fintech neobank payments startup funding",
    "India edtech healthtech agritech startup",
    "India startup IPO listing pre-IPO",
    "India accelerator incubator YCombinator startup",
    "India SaaS B2B software startup growth ARR",
    "India startup layoff pivot shutdown 2025",
]


class IndiaStartupIngestor(NewsDataIngestor):

    def __init__(self, api_key: str):
        super().__init__(api_key, domain="india_corporate")

    def fetch(self, max_articles: int = 40) -> List[BaseRawModel]:
        results: List[BaseRawModel] = []
        seen: set = set()

        for query in STARTUP_QUERIES:
            if len(results) >= max_articles:
                break
            articles = self.fetch_articles(
                query    = query,
                category = "business,technology",
                country  = "in",
                language = "en",
                max_pages = 1,
            )
            for a in articles:
                if a.source_url not in seen and a.text.strip():
                    seen.add(a.source_url)
                    results.append(a)

        return results[:max_articles]
