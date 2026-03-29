"""
GDELTIngestor — queries the GDELT 2.0 Doc API for geopolitical event news.
Free, no API key. Rate-limited — uses 1.5s delay between queries.
"""

from __future__ import annotations
import time
from typing import List

import requests

from global_graph.domains.base_raw_model import BaseRawModel

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Simple unquoted queries — GDELT handles these more reliably than
# multi-term quoted OR expressions (from Paqshi reference)
QUERIES = [
    "India China border military",
    "India Pakistan conflict",
    "India foreign policy diplomacy",
    "Russia Ukraine war",
    "Israel Gaza conflict",
    "NATO summit alliance",
    "sanctions Iran Russia",
    "Quad Indo-Pacific security",
    "SCO BRICS summit",
    "India defence DRDO HAL",
    "Kashmir Line Control",
    "South China Sea dispute",
    "nuclear missile test",
    "coup protest uprising",
    "India US relations",
]

DELAY_SECONDS = 1.5    # polite rate-limit for free GDELT service


class GDELTIngestor:

    def fetch(self, max_results: int = 60, days_back: int = 3) -> List[BaseRawModel]:
        results: List[BaseRawModel] = []
        seen: set = set()

        for query in QUERIES:
            if len(results) >= max_results:
                break

            try:
                resp = requests.get(GDELT_URL, params={
                    "query":      query,
                    "mode":       "artlist",        # lowercase per Paqshi reference
                    "maxrecords": 10,
                    "format":     "json",
                    "timespan":   f"{days_back}d",  # e.g. "3d" not "2weeks"
                    "sort":       "DateDesc",
                }, timeout=20)
                resp.raise_for_status()

                # GDELT occasionally returns empty body instead of JSON
                text = resp.text.strip()
                if not text:
                    time.sleep(DELAY_SECONDS)
                    continue

                data = resp.json()
            except Exception as e:
                print(f"[GDELT] query '{query}' error: {e}")
                time.sleep(DELAY_SECONDS)
                continue

            fetched = 0
            for art in data.get("articles", []):
                url    = art.get("url", "")
                title  = art.get("title", "")
                domain_src = art.get("domain", "")
                seendate   = art.get("seendate", "")

                if not url or url in seen:
                    continue
                seen.add(url)
                fetched += 1

                text_str = (
                    f"[GDELT] {title}. "
                    f"Source: {domain_src}. "
                    f"Date: {seendate}. URL: {url}"
                )
                results.append(BaseRawModel(
                    text       = text_str,
                    source_url = url,
                    domain     = "geopolitics",
                    title      = title,
                    published  = seendate or None,
                    tags       = ["GDELT", "geopolitics"] + query.lower().split()[:3],
                ))

            if fetched:
                print(f"[GDELT] '{query}' → {fetched} articles")

            time.sleep(DELAY_SECONDS)

        print(f"[GDELT] Total: {len(results)} geopolitics articles")
        return results
