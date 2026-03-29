"""
IndiaFinanceIngestor — Indian stock market and finance data:
  • NewsData.io (stock market news)
  • NSE/BSE corporate announcement news
"""

from __future__ import annotations
from typing import List

from global_graph.domains.base_raw_model import BaseRawModel
from global_graph.ingestors.newsdata_ingestor import NewsDataIngestor
from india_graph.ingestors.data_sources.nse_bse_news import NSEBSENewsIngestor

FINANCE_QUERIES = [
    "NSE BSE stock market India rally",
    "NIFTY SENSEX index India market",
    "IPO listing India stock exchange 2025",
    "FII DII investment India market flows",
    "promoter shareholding stake India company",
    "quarterly results earnings India company",
    "India mutual fund NFO NAV",
    "Tata Reliance Adani HDFC Infosys TCS share price",
    "India bond yield gilt market RBI",
    "India commodities gold silver MCX",
]


class IndiaFinanceIngestor(NewsDataIngestor):

    def __init__(self, api_key: str):
        super().__init__(api_key, domain="india_finance")
        self._nse_bse = NSEBSENewsIngestor(api_key)

    def fetch(self, max_articles: int = 80) -> List[BaseRawModel]:
        seen: set = set()
        results: List[BaseRawModel] = []

        def _add(items: List[BaseRawModel]):
            for item in items:
                if item.source_url not in seen and item.text.strip():
                    seen.add(item.source_url)
                    results.append(item)

        # 1. NewsData market news
        for query in FINANCE_QUERIES:
            if len(results) >= max_articles:
                break
            _add(self.fetch_articles(
                query    = query,
                category = "business",
                country  = "in",
                language = "en",
                max_pages = 1,
            ))

        # 2. NSE/BSE specific exchange news
        try:
            _add(self._nse_bse.fetch())
        except Exception as e:
            print(f"[IndiaFinanceIngestor] NSE/BSE failed: {e}")

        return results[:max_articles]
