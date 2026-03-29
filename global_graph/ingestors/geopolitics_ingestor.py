"""
GeopoliticsIngestor — fetches geopolitical intelligence from multiple sources:
  • NewsData.io (news articles)
  • GDELT 2.0 Doc API (event-based signal extraction)
  • ACLED (armed conflict events, requires credentials)
  • SIPRI (arms transfers seed data + reports)
  • Wikidata (nations and alliances reference data)
"""

from __future__ import annotations
from typing import List

from global_graph.domains.base_raw_model import BaseRawModel
from global_graph.ingestors.newsdata_ingestor import NewsDataIngestor
from global_graph.ingestors.data_sources.gdelt import GDELTIngestor
from global_graph.ingestors.data_sources.acled import ACLEDIngestor
from global_graph.ingestors.data_sources.sipri import SIPRIIngestor
from global_graph.ingestors.data_sources.wikidata_nations import WikidataNationsIngestor

GEOPOLITICS_QUERIES = [
    "sanctions war conflict diplomacy",
    "trade war tariff embargo",
    "NATO military alliance",
    "United Nations resolution",
    "election government coup",
    "border dispute territorial",
    "nuclear weapons arms",
    "refugee migration asylum",
    "India foreign policy bilateral",
    "China Russia US strategic competition",
    "Middle East Gulf region stability",
    "Africa investment infrastructure China",
    "BRICS SCO Quad multilateral",
    "India China border LAC Ladakh",
    "Pakistan India relations ceasefire",
]


class GeopoliticsIngestor(NewsDataIngestor):

    def __init__(
        self,
        api_key:       str,
        acled_email:   str = "",
        acled_password: str = "",
    ):
        super().__init__(api_key, domain="geopolitics")
        self._gdelt    = GDELTIngestor()
        self._acled    = ACLEDIngestor(acled_email, acled_password)
        self._sipri    = SIPRIIngestor()
        self._wikidata = WikidataNationsIngestor()

    def fetch(self, max_articles: int = 100) -> List[BaseRawModel]:
        seen: set = set()
        results: List[BaseRawModel] = []

        def _add(items: List[BaseRawModel]):
            for item in items:
                if item.source_url not in seen and item.text.strip():
                    seen.add(item.source_url)
                    results.append(item)

        # 1. NewsData news
        for query in GEOPOLITICS_QUERIES:
            if len(results) >= max_articles:
                break
            _add(self.fetch_articles(
                query    = query,
                category = "politics,world",
                language = "en",
                max_pages = 1,
            ))

        # 2. GDELT signals
        try:
            _add(self._gdelt.fetch())
        except Exception as e:
            print(f"[GeopoliticsIngestor] GDELT failed: {e}")

        # 3. ACLED conflict events (skips silently if no credentials)
        try:
            _add(self._acled.fetch())
        except Exception as e:
            print(f"[GeopoliticsIngestor] ACLED failed: {e}")

        # 4. SIPRI arms transfers
        try:
            _add(self._sipri.fetch())
        except Exception as e:
            print(f"[GeopoliticsIngestor] SIPRI failed: {e}")

        # 5. Wikidata reference data (nations + alliances)
        try:
            _add(self._wikidata.fetch())
        except Exception as e:
            print(f"[GeopoliticsIngestor] Wikidata failed: {e}")

        return results[:max_articles]
