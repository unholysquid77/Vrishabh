"""
NASAGISTEMPIngestor — pulls global temperature anomaly time-series from NASA GISTEMP.
Free, no API key.
"""

from __future__ import annotations
import csv
from io import StringIO
from typing import List

import requests

from global_graph.domains.base_raw_model import BaseRawModel

DATA_URL = "https://data.giss.nasa.gov/gistemp/tabledata_v4/GLB.Ts+dSST.csv"


class NASAGISTEMPIngestor:

    def fetch(self) -> List[BaseRawModel]:
        try:
            resp = requests.get(DATA_URL, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            print(f"[NASA GISTEMP] fetch failed: {e}")
            return []

        rows = list(csv.reader(StringIO(resp.text)))
        results: List[BaseRawModel] = []

        for row in rows[2:17]:           # rows 2-16 = last 15 years of data
            if not row or not row[0].strip().isdigit():
                continue
            year = row[0].strip()
            if len(row) < 14:
                continue
            annual = row[13].strip()
            if not annual or annual in ("***", ""):
                continue

            text = (
                f"NASA GISTEMP global surface temperature anomaly for {year}: "
                f"{annual}°C above 1951-1980 baseline. "
                f"Source: NASA Goddard Institute for Space Studies."
            )
            results.append(BaseRawModel(
                text       = text,
                source_url = DATA_URL,
                domain     = "climate",
                title      = f"Global Temperature Anomaly {year}",
                published  = f"{year}-01-01T00:00:00",
                tags       = ["temperature", "climate", "NASA", "GISTEMP", year],
            ))

        return results
