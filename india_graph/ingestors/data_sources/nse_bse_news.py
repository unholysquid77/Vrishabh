"""
NSEBSENewsIngestor — NSE/BSE corporate announcements, block deals, and exchange filings
via NewsData.io. NSE/BSE don't expose free announcement APIs, so we use targeted news queries.
"""

from __future__ import annotations
from typing import List

from global_graph.domains.base_raw_model import BaseRawModel
from global_graph.ingestors.newsdata_ingestor import NewsDataIngestor

NSE_BSE_QUERIES = [
    "NSE BSE corporate announcement India stock exchange 2025",
    "India block deal bulk deal promoter stake",
    "India insider trading SEBI adjudication",
    "India company board meeting dividend record date",
    "India rights issue preferential allotment QIP",
    "India circuit breaker upper lower limit NSE",
    "India IPO listing grey market premium",
    "India FII DII net buying selling data",
    "India mutual fund SIP inflow outflow AUM",
    "India derivatives F&O open interest rollover",
]


class NSEBSENewsIngestor(NewsDataIngestor):

    def __init__(self, api_key: str):
        super().__init__(api_key, domain="india_finance")

    def fetch(self, max_articles: int = 50) -> List[BaseRawModel]:
        results: List[BaseRawModel] = []
        seen: set = set()

        for query in NSE_BSE_QUERIES:
            if len(results) >= max_articles:
                break
            articles = self.fetch_articles(
                query    = query,
                category = "business",
                country  = "in",
                language = "en",
                max_pages = 1,
            )
            for a in articles:
                if a.source_url not in seen and a.text.strip():
                    seen.add(a.source_url)
                    results.append(a)

        return results[:max_articles]
