"""
WorldBankClimateIngestor — pulls climate-relevant development indicators from World Bank API.
Free, no API key.
"""

from __future__ import annotations
from datetime import datetime
from typing import List

import requests

from global_graph.domains.base_raw_model import BaseRawModel

BASE_URL = "https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"

# (indicator_code, human_label)
INDICATORS = [
    ("EN.ATM.CO2E.PC",    "CO2 emissions per capita (metric tons)"),
    ("EG.FEC.RNEW.ZS",    "Renewable energy share of total final energy consumption (%)"),
    ("AG.LND.FRST.ZS",    "Forest area (% of land area)"),
    ("EN.ATM.METH.KT.CE", "Methane emissions (kt of CO2 equivalent)"),
    ("EG.USE.PCAP.KG.OE", "Energy use per capita (kg of oil equivalent)"),
    ("SP.POP.TOTL",        "Total population"),
    ("NY.GDP.PCAP.CD",     "GDP per capita (USD)"),
]

# Key emitters + India focus
COUNTRIES = ["IN", "CN", "US", "DE", "BR", "RU", "GB", "JP", "SA", "ZA"]


class WorldBankClimateIngestor:

    def fetch(self) -> List[BaseRawModel]:
        results: List[BaseRawModel] = []

        for country in COUNTRIES:
            country_rows: List[str] = []

            for indicator_code, label in INDICATORS:
                url = BASE_URL.format(country=country, indicator=indicator_code)
                try:
                    resp = requests.get(url, params={
                        "format": "json",
                        "mrv":    "5",      # most recent 5 values
                        "per_page": "5",
                    }, timeout=15)
                    resp.raise_for_status()
                    payload = resp.json()
                except Exception:
                    continue

                if len(payload) < 2 or not payload[1]:
                    continue

                for entry in payload[1]:
                    year  = entry.get("date")
                    value = entry.get("value")
                    if value is None:
                        continue
                    country_rows.append(f"{label} ({year}): {value:.2f}" if isinstance(value, float) else f"{label} ({year}): {value}")
                    break  # most recent only

            if not country_rows:
                continue

            text = (
                f"World Bank climate & energy indicators for {country} "
                f"(latest available data):\n" + "\n".join(country_rows)
            )
            results.append(BaseRawModel(
                text       = text,
                source_url = f"https://data.worldbank.org/country/{country.lower()}",
                domain     = "climate",
                title      = f"World Bank Indicators: {country}",
                published  = datetime.utcnow().isoformat(),
                tags       = ["world_bank", "climate", "energy", "emissions", country.lower()],
            ))

        return results
