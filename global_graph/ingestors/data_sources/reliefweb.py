"""
ReliefWebIngestor — fetches humanitarian disaster reports from ReliefWeb API.
Free, no API key. Uses appname query param as required by ReliefWeb TOS.
"""

from __future__ import annotations
from typing import List

import requests

from global_graph.domains.base_raw_model import BaseRawModel

API_URL  = "https://api.reliefweb.int/v2/reports"
APP_NAME = "paqshi_analytics306BdgL6oxtDXr"

DISASTER_TYPES = ["Flood", "Storm", "Wildfire", "Drought", "Heat Wave", "Cyclone", "Earthquake"]


class ReliefWebIngestor:

    def fetch(self, limit: int = 30) -> List[BaseRawModel]:
        results: List[BaseRawModel] = []

        try:
            resp = requests.post(
                f"{API_URL}?appname={APP_NAME}",
                json={
                    "limit": limit,
                    "sort":  ["date:desc"],
                    "fields": {
                        "include": ["title", "body", "source", "url", "date"],
                    },
                    "filter": {
                        "field": "disaster_type.name",   # correct field name
                        "value": DISASTER_TYPES,
                    },
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[ReliefWeb] fetch failed: {e}")
            return []

        items = data.get("data", [])
        print(f"[ReliefWeb] Fetched {len(items)} disaster reports")

        for item in items:
            fields = item.get("fields", {})
            title  = fields.get("title", "")
            body   = (fields.get("body") or "")[:600]
            sources = ", ".join(s.get("name", "") for s in (fields.get("source") or []))
            url    = fields.get("url", "")
            date_block = fields.get("date") or {}
            date   = date_block.get("original") or date_block.get("created") or ""

            if not title:
                continue

            text = f"[ReliefWeb Disaster] {title}\nSource: {sources}\n{body}"
            results.append(BaseRawModel(
                text       = text,
                source_url = url or API_URL,
                domain     = "climate",
                title      = title,
                published  = date,
                tags       = ["ReliefWeb", "disaster", "humanitarian"],
            ))

        return results
