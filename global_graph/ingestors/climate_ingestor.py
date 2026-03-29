"""
ClimateIngestor — fetches climate, energy, and environmental data from multiple sources:
  • NewsData.io (news articles)
  • NASA GISTEMP (temperature anomalies)
  • Open-Meteo (weather forecasts)
  • World Bank (climate indicators)
  • ReliefWeb (disaster reports)
"""

from __future__ import annotations
from typing import List

from global_graph.domains.base_raw_model import BaseRawModel
from global_graph.ingestors.newsdata_ingestor import NewsDataIngestor
from global_graph.ingestors.data_sources.nasa_gistemp import NASAGISTEMPIngestor
from global_graph.ingestors.data_sources.open_meteo import OpenMeteoIngestor
from global_graph.ingestors.data_sources.world_bank_climate import WorldBankClimateIngestor
from global_graph.ingestors.data_sources.reliefweb import ReliefWebIngestor

CLIMATE_QUERIES = [
    "climate change global warming emissions",
    "renewable energy solar wind",
    "carbon credits net zero",
    "extreme weather flood drought",
    "COP climate agreement Paris",
    "oil gas fossil fuel",
    "deforestation biodiversity",
    "electric vehicle EV battery",
    "heatwave cyclone wildfire disaster",
    "IPCC climate report carbon budget",
]


class ClimateIngestor(NewsDataIngestor):

    def __init__(self, api_key: str):
        super().__init__(api_key, domain="climate")
        self._nasa      = NASAGISTEMPIngestor()
        self._meteo     = OpenMeteoIngestor()
        self._worldbank = WorldBankClimateIngestor()
        self._reliefweb = ReliefWebIngestor()

    def fetch(self, max_articles: int = 80) -> List[BaseRawModel]:
        seen: set = set()
        results: List[BaseRawModel] = []

        def _add(items: List[BaseRawModel]):
            for item in items:
                if item.source_url not in seen and item.text.strip():
                    seen.add(item.source_url)
                    results.append(item)

        # 1. NewsData news
        for query in CLIMATE_QUERIES:
            if len(results) >= max_articles:
                break
            _add(self.fetch_articles(
                query    = query,
                category = "environment,science",
                language = "en",
                max_pages = 1,
            ))

        # 2. NASA GISTEMP temperature anomalies
        try:
            _add(self._nasa.fetch())
        except Exception as e:
            print(f"[ClimateIngestor] NASA failed: {e}")

        # 3. Open-Meteo weather snapshots
        try:
            _add(self._meteo.fetch())
        except Exception as e:
            print(f"[ClimateIngestor] Open-Meteo failed: {e}")

        # 4. World Bank climate indicators
        try:
            _add(self._worldbank.fetch())
        except Exception as e:
            print(f"[ClimateIngestor] World Bank failed: {e}")

        # 5. ReliefWeb disaster reports
        try:
            _add(self._reliefweb.fetch())
        except Exception as e:
            print(f"[ClimateIngestor] ReliefWeb failed: {e}")

        return results[:max_articles]
