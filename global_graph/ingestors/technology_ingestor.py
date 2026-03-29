"""
TechnologyIngestor — fetches global tech, AI, and research data from multiple sources:
  • NewsData.io (news articles)
  • ArXiv (academic preprints)
  • OpenAlex (research papers with citations)
"""

from __future__ import annotations
from typing import List

from global_graph.domains.base_raw_model import BaseRawModel
from global_graph.ingestors.newsdata_ingestor import NewsDataIngestor
from global_graph.ingestors.data_sources.openalex import OpenAlexIngestor

TECHNOLOGY_QUERIES = [
    "artificial intelligence machine learning",
    "semiconductor chip fab TSMC Intel",
    "cybersecurity hack breach ransomware",
    "cloud computing SaaS hyperscaler",
    "startup funding venture capital unicorn",
    "quantum computing qubit error correction",
    "social media regulation tech antitrust",
    "robotics automation factory industry",
    "AI policy regulation EU CHIPS Act",
    "NVIDIA GPU data centre AI inference",
    "OpenAI ChatGPT Anthropic Gemini model",
    "India tech ISRO satellite defence DRDO",
    "China tech ban export controls chips",
    "5G 6G telecom spectrum",
    "biotech CRISPR gene therapy pharma",
]


class TechnologyIngestor(NewsDataIngestor):

    def __init__(self, api_key: str):
        super().__init__(api_key, domain="technology")
        self._openalex = OpenAlexIngestor()

    def fetch(self, max_articles: int = 100) -> List[BaseRawModel]:
        seen: set = set()
        results: List[BaseRawModel] = []

        def _add(items: List[BaseRawModel]):
            for item in items:
                if item.source_url not in seen and item.text.strip():
                    seen.add(item.source_url)
                    results.append(item)

        # 1. NewsData news
        for query in TECHNOLOGY_QUERIES:
            if len(results) >= max_articles:
                break
            _add(self.fetch_articles(
                query    = query,
                category = "technology,science",
                language = "en",
                max_pages = 1,
            ))

        # 2. OpenAlex research papers
        try:
            _add(self._openalex.fetch())
        except Exception as e:
            print(f"[TechnologyIngestor] OpenAlex failed: {e}")

        return results[:max_articles]
