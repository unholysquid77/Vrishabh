"""
IndiaPolicyIngestor — Indian government policy, RBI, SEBI, and regulatory news:
  • NewsData.io (policy news)
  • RBI press releases / MPC decisions (RSS)
  • SEBI circulars and orders (RSS + targeted news)
"""

from __future__ import annotations
from typing import List

from global_graph.domains.base_raw_model import BaseRawModel
from global_graph.ingestors.newsdata_ingestor import NewsDataIngestor
from india_graph.ingestors.data_sources.rbi_releases import RBIReleasesIngestor
from india_graph.ingestors.data_sources.sebi_news import SEBINewsIngestor

POLICY_QUERIES = [
    "RBI repo rate monetary policy India decision",
    "SEBI regulation circular India market",
    "Union Budget India tax fiscal",
    "India government policy scheme ministry",
    "PLI production linked incentive India",
    "IRDAI insurance India regulation",
    "India economic policy reform",
    "Make in India startup scheme government",
    "NPCI UPI payment India digital",
    "India import duty tariff GST change",
]


class IndiaPolicyIngestor(NewsDataIngestor):

    def __init__(self, api_key: str):
        super().__init__(api_key, domain="india_policy")
        self._rbi  = RBIReleasesIngestor()
        self._sebi = SEBINewsIngestor(api_key)

    def fetch(self, max_articles: int = 80) -> List[BaseRawModel]:
        seen: set = set()
        results: List[BaseRawModel] = []

        def _add(items: List[BaseRawModel]):
            for item in items:
                if item.source_url not in seen and item.text.strip():
                    seen.add(item.source_url)
                    results.append(item)

        # 1. NewsData policy news
        for query in POLICY_QUERIES:
            if len(results) >= max_articles:
                break
            _add(self.fetch_articles(
                query    = query,
                category = "politics,business",
                country  = "in",
                language = "en",
                max_pages = 1,
            ))

        # 2. RBI press releases / MPC
        try:
            _add(self._rbi.fetch())
        except Exception as e:
            print(f"[IndiaPolicyIngestor] RBI failed: {e}")

        # 3. SEBI circulars and enforcement
        try:
            _add(self._sebi.fetch())
        except Exception as e:
            print(f"[IndiaPolicyIngestor] SEBI failed: {e}")

        return results[:max_articles]
