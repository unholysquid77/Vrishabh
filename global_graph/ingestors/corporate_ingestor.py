"""
CorporateIngestor — fetches global corporate events from multiple sources:
  • NewsData.io (news articles)
  • SEC EDGAR (8-K material events + 13F institutional holdings)
"""

from __future__ import annotations
from typing import List

from global_graph.domains.base_raw_model import BaseRawModel
from global_graph.ingestors.newsdata_ingestor import NewsDataIngestor
from global_graph.ingestors.data_sources.sec_edgar import SECEdgarIngestor

CORPORATE_QUERIES = [
    "merger acquisition deal",
    "IPO listing stock market",
    "earnings revenue profit loss quarterly",
    "CEO CFO executive leadership appointment",
    "supply chain disruption shortage",
    "product launch innovation",
    "layoff workforce restructuring",
    "joint venture partnership",
    "bankruptcy insolvency Chapter 11",
    "private equity LBO leveraged buyout",
    "activist investor proxy fight shareholder",
    "antitrust regulatory approval deal",
    "share buyback dividend special payout",
    "credit rating downgrade upgrade Moody Fitch",
]


class CorporateIngestor(NewsDataIngestor):

    def __init__(self, api_key: str):
        super().__init__(api_key, domain="corporate")
        self._sec = SECEdgarIngestor()

    def fetch(self, max_articles: int = 80) -> List[BaseRawModel]:
        seen: set = set()
        results: List[BaseRawModel] = []

        def _add(items: List[BaseRawModel]):
            for item in items:
                if item.source_url not in seen and item.text.strip():
                    seen.add(item.source_url)
                    results.append(item)

        # 1. NewsData news
        for query in CORPORATE_QUERIES:
            if len(results) >= max_articles:
                break
            _add(self.fetch_articles(
                query    = query,
                category = "business",
                language = "en",
                max_pages = 1,
            ))

        # 2. SEC EDGAR filings (8-K + 13F)
        try:
            _add(self._sec.fetch())
        except Exception as e:
            print(f"[CorporateIngestor] SEC EDGAR failed: {e}")

        return results[:max_articles]
