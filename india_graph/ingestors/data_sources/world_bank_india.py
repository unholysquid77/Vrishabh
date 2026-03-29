"""
WorldBankIndiaIngestor — pulls India-specific development and macro indicators
from the World Bank API. Free, no API key.
"""

from __future__ import annotations
from datetime import datetime
from typing import List

import requests

from global_graph.domains.base_raw_model import BaseRawModel

BASE_URL = "https://api.worldbank.org/v2/country/IN/indicator/{indicator}"

INDICATORS = [
    ("NY.GDP.MKTP.KD.ZG",  "GDP growth rate (annual %)"),
    ("FP.CPI.TOTL.ZG",     "Inflation / CPI (annual %)"),
    ("NE.TRD.GNFS.ZS",     "Trade (% of GDP)"),
    ("BX.KLT.DINV.CD.WD",  "FDI inflows (USD)"),
    ("GC.DOD.TOTL.GD.ZS",  "Central government debt (% of GDP)"),
    ("BN.CAB.XOKA.GD.ZS",  "Current account balance (% of GDP)"),
    ("SP.POP.TOTL",         "Population"),
    ("SL.UEM.TOTL.ZS",     "Unemployment rate (%)"),
    ("EG.USE.PCAP.KG.OE",  "Energy use per capita (kg of oil equivalent)"),
    ("SE.XPD.TOTL.GD.ZS",  "Government expenditure on education (% of GDP)"),
    ("IC.BUS.EASE.XQ",     "Ease of doing business rank"),
    ("EN.ATM.CO2E.PC",     "CO2 emissions per capita (metric tons)"),
]


class WorldBankIndiaIngestor:

    def fetch(self) -> List[BaseRawModel]:
        results: List[BaseRawModel] = []
        rows: List[str] = []

        for indicator_code, label in INDICATORS:
            url = BASE_URL.format(indicator=indicator_code)
            try:
                resp = requests.get(url, params={
                    "format":   "json",
                    "mrv":      "3",
                    "per_page": "3",
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
                formatted = f"{value:.2f}" if isinstance(value, float) else str(value)
                rows.append(f"{label} ({year}): {formatted}")
                break  # most recent year only

        if rows:
            results.append(BaseRawModel(
                text       = (
                    "World Bank India macroeconomic indicators (latest available):\n"
                    + "\n".join(rows)
                ),
                source_url = "https://data.worldbank.org/country/india",
                domain     = "india_economy",
                title      = "India Macro Indicators – World Bank",
                published  = datetime.utcnow().isoformat(),
                tags       = ["world_bank", "india", "macro", "economy", "GDP", "inflation"],
            ))

        return results
