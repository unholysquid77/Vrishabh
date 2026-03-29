"""
IndiaMacroMOSPIIngestor — India macro data: IIP, PMI, CPI, WPI, trade stats.
Uses NewsData.io (MOSPI/RBI/CMIE have no free REST APIs; authoritative data
releases are best captured via news at publication time).
"""

from __future__ import annotations
from typing import List

from global_graph.domains.base_raw_model import BaseRawModel
from global_graph.ingestors.newsdata_ingestor import NewsDataIngestor

MACRO_QUERIES = [
    "India IIP Index Industrial Production data release",
    "India PMI manufacturing services Purchasing Managers",
    "India CPI consumer price index inflation data",
    "India WPI wholesale price index data",
    "India GDP quarterly growth MOSPI CSO",
    "India trade deficit surplus exports imports data",
    "India GST collection revenue monthly",
    "India core sector output eight infrastructure industries",
    "India current account deficit CAD RBI data",
    "India fiscal deficit budget target",
    "India forex reserves RBI foreign exchange",
    "India rupee dollar exchange rate RBI intervention",
]


class IndiaMacroMOSPIIngestor(NewsDataIngestor):

    def __init__(self, api_key: str):
        super().__init__(api_key, domain="india_economy")

    def fetch(self, max_articles: int = 50) -> List[BaseRawModel]:
        results: List[BaseRawModel] = []
        seen: set = set()

        for query in MACRO_QUERIES:
            if len(results) >= max_articles:
                break
            articles = self.fetch_articles(
                query    = query,
                category = "business,top",
                country  = "in",
                language = "en",
                max_pages = 1,
            )
            for a in articles:
                if a.source_url not in seen and a.text.strip():
                    seen.add(a.source_url)
                    results.append(a)

        return results[:max_articles]
