"""
IndiaWhaleWatchIngestor — institutional and large-trader flow monitoring for Indian markets.

Tracks:
  • FII / DII daily net buy/sell flows
  • NSE/BSE bulk deal and block deal disclosures
  • Promoter buying/selling activity
  • Large institutional accumulation or distribution patterns

Data source: NewsData.io (free tier, no additional API key needed)
"""

from __future__ import annotations
from typing import List

from global_graph.domains.base_raw_model import BaseRawModel
from global_graph.ingestors.newsdata_ingestor import NewsDataIngestor


WHALE_WATCH_QUERIES = [
    "FII DII net buy sell India stock market today",
    "bulk deal block deal NSE BSE India today",
    "promoter buying selling stake India listed company",
    "institutional investor accumulation distribution India equities",
    "foreign portfolio investor FPI flows India",
    "mutual fund NFO SIP investment India inflows outflows",
    "anchor investor IPO allotment India",
    "SEBI bulk deal disclosure insider buying India",
    "large block trade NSE 52 week high low India",
    "smart money inflow India stock market sector",
]


class IndiaWhaleWatchIngestor(NewsDataIngestor):
    """
    Monitors large institutional and whale-trader activity in Indian markets.
    Plugs into the IndiaCorporateIngestor as an additional data source.
    """

    def __init__(self, api_key: str):
        super().__init__(api_key, domain="india_corporate")

    def fetch(self, max_articles: int = 30) -> List[BaseRawModel]:
        seen:    set               = set()
        results: List[BaseRawModel] = []

        def _add(items: List[BaseRawModel]):
            for item in items:
                if item.source_url not in seen and item.text.strip():
                    seen.add(item.source_url)
                    results.append(item)

        for query in WHALE_WATCH_QUERIES:
            if len(results) >= max_articles:
                break
            try:
                _add(self.fetch_articles(
                    query     = query,
                    category  = "business",
                    country   = "in",
                    language  = "en",
                    max_pages = 1,
                ))
            except Exception as e:
                print(f"[WhaleWatch] Query '{query[:40]}' failed: {e}")

        return results[:max_articles]
