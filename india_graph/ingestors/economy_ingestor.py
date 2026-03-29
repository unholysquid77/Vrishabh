"""
IndiaEconomyIngestor — Indian macroeconomic data and trends:
  • NewsData.io (economy news)
  • World Bank India indicators
  • MOSPI/RBI data releases via targeted news
"""

from __future__ import annotations
from typing import List

from global_graph.domains.base_raw_model import BaseRawModel
from global_graph.ingestors.newsdata_ingestor import NewsDataIngestor
from india_graph.ingestors.data_sources.world_bank_india import WorldBankIndiaIngestor
from india_graph.ingestors.data_sources.india_macro_mospi import IndiaMacroMOSPIIngestor

ECONOMY_QUERIES = [
    "India GDP growth rate economy",
    "India inflation CPI WPI data",
    "India IIP PMI manufacturing index",
    "India FDI FPI foreign investment inflow",
    "India exports imports trade deficit",
    "India current account fiscal deficit",
    "India infrastructure project highway port",
    "India rupee dollar exchange rate economy",
    "India banking credit growth NPA",
    "India agriculture food production monsoon",
]


class IndiaEconomyIngestor(NewsDataIngestor):

    def __init__(self, api_key: str):
        super().__init__(api_key, domain="india_economy")
        self._worldbank = WorldBankIndiaIngestor()
        self._mospi     = IndiaMacroMOSPIIngestor(api_key)

    def fetch(self, max_articles: int = 80) -> List[BaseRawModel]:
        seen: set = set()
        results: List[BaseRawModel] = []

        def _add(items: List[BaseRawModel]):
            for item in items:
                if item.source_url not in seen and item.text.strip():
                    seen.add(item.source_url)
                    results.append(item)

        # 1. NewsData economy news
        for query in ECONOMY_QUERIES:
            if len(results) >= max_articles:
                break
            _add(self.fetch_articles(
                query    = query,
                category = "business,top",
                country  = "in",
                language = "en",
                max_pages = 1,
            ))

        # 2. World Bank India indicators
        try:
            _add(self._worldbank.fetch())
        except Exception as e:
            print(f"[IndiaEconomyIngestor] World Bank failed: {e}")

        # 3. MOSPI/macro data release news
        try:
            _add(self._mospi.fetch())
        except Exception as e:
            print(f"[IndiaEconomyIngestor] MOSPI failed: {e}")

        return results[:max_articles]
