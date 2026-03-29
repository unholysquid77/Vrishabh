"""
IndiaCorporateIngestor — Indian corporate events, startups, regulatory filings,
and institutional flow (whale watch):
  • NewsData.io (corporate news)
  • MCA India regulatory filings and NCLT orders
  • India startup funding and unicorn news
  • WhaleWatch: FII/DII flows, bulk/block deals, promoter activity
"""

from __future__ import annotations
from typing import List

from global_graph.domains.base_raw_model import BaseRawModel
from global_graph.ingestors.newsdata_ingestor import NewsDataIngestor
from india_graph.ingestors.data_sources.mca_india import MCAIndiaIngestor
from india_graph.ingestors.data_sources.india_startup import IndiaStartupIngestor
from india_graph.ingestors.data_sources.whale_watch import IndiaWhaleWatchIngestor

CORPORATE_QUERIES = [
    "India startup funding unicorn valuation 2025",
    "India merger acquisition deal corporate",
    "India company earnings profit revenue quarterly",
    "India promoter stake sale block deal",
    "India conglomerate Tata Adani Birla Mahindra",
    "India analyst rating target price buy sell",
    "India company expansion capex investment",
    "India corporate restructuring demerger spinoff",
    "India conglomerate holding company listed",
    "India PSU disinvestment privatisation stake sale",
]


class IndiaCorporateIngestor(NewsDataIngestor):

    def __init__(self, api_key: str):
        super().__init__(api_key, domain="india_corporate")
        self._mca        = MCAIndiaIngestor(api_key)
        self._startup    = IndiaStartupIngestor(api_key)
        self._whale      = IndiaWhaleWatchIngestor(api_key)

    def fetch(self, max_articles: int = 80) -> List[BaseRawModel]:
        seen: set = set()
        results: List[BaseRawModel] = []

        def _add(items: List[BaseRawModel]):
            for item in items:
                if item.source_url not in seen and item.text.strip():
                    seen.add(item.source_url)
                    results.append(item)

        # 1. NewsData corporate news
        for query in CORPORATE_QUERIES:
            if len(results) >= max_articles:
                break
            _add(self.fetch_articles(
                query    = query,
                category = "business",
                country  = "in",
                language = "en",
                max_pages = 1,
            ))

        # 2. MCA India regulatory filings + NCLT
        try:
            _add(self._mca.fetch())
        except Exception as e:
            print(f"[IndiaCorporateIngestor] MCA failed: {e}")

        # 3. Startup funding + unicorn news
        try:
            _add(self._startup.fetch())
        except Exception as e:
            print(f"[IndiaCorporateIngestor] Startup failed: {e}")

        # 4. Institutional flow: FII/DII, bulk/block deals, promoter activity
        try:
            _add(self._whale.fetch())
        except Exception as e:
            print(f"[IndiaCorporateIngestor] WhaleWatch failed: {e}")

        return results[:max_articles]
