"""
MCAIndiaIngestor — Indian Ministry of Corporate Affairs filings and regulatory news.
Uses NewsData.io filtered to India with MCA-specific keywords.
Also fetches NCLT/NCLAT orders via news as MCA's portal has no public API.
"""

from __future__ import annotations
from typing import List

from global_graph.domains.base_raw_model import BaseRawModel
from global_graph.ingestors.newsdata_ingestor import NewsDataIngestor

MCA_QUERIES = [
    "MCA Ministry Corporate Affairs India filing 2025",
    "Registrar of Companies India director appointment resignation",
    "NCLT NCLAT order India insolvency IBC",
    "India company incorporation AGM board resolution",
    "India corporate fraud SFIO investigation",
    "India demerger spinoff restructuring NCLT approval",
    "ROC notice penalty India company compliance",
    "India corporate governance ESG board diversity",
]


class MCAIndiaIngestor(NewsDataIngestor):

    def __init__(self, api_key: str):
        super().__init__(api_key, domain="india_corporate")

    def fetch(self, max_articles: int = 40) -> List[BaseRawModel]:
        results: List[BaseRawModel] = []
        seen: set = set()

        for query in MCA_QUERIES:
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
