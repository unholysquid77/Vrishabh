"""
OpenAlexIngestor — academic research papers from OpenAlex API.
Free, 100k requests/day, no API key required.
"""

from __future__ import annotations
import time
from datetime import datetime, timedelta
from typing import List

import requests

from global_graph.domains.base_raw_model import BaseRawModel

BASE_URL = "https://api.openalex.org/works"
EMAIL    = "vrishabh-graph@example.com"   # polite pool (faster rate)

# (concept_id, label) — OpenAlex concept IDs
TOPICS = [
    ("C154945302", "Artificial intelligence"),
    ("C11413529",  "Semiconductor device"),
    ("C21547014",  "Quantum computing"),
    ("C185592680", "Chemistry / CRISPR"),
    ("C2522767166","Deep learning"),
    ("C41008148",  "Computer security"),
    ("C2776943663","Robotics"),
    ("C126255220", "Nuclear engineering"),
    ("C62520636",  "Machine learning"),
]

INDIA_QUERIES = [
    "ISRO satellite launch India",
    "DRDO India defence research",
    "India semiconductor manufacturing",
    "Indian Institute Technology research",
]


class OpenAlexIngestor:

    def fetch(self, max_per_topic: int = 3) -> List[BaseRawModel]:
        results: List[BaseRawModel] = []
        seen: set = set()
        since = (datetime.utcnow() - timedelta(days=60)).strftime("%Y-%m-%d")

        # Concept-based fetch
        for concept_id, label in TOPICS:
            try:
                resp = requests.get(BASE_URL, params={
                    "filter":     f"concepts.id:{concept_id},from_publication_date:{since}",
                    "sort":       "cited_by_count:desc",
                    "per-page":   max_per_topic,
                    "select":     "id,title,abstract_inverted_index,publication_date,authorships,primary_location,cited_by_count",
                    "mailto":     EMAIL,
                }, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"[OpenAlex] concept {label} failed: {e}")
                time.sleep(1)
                continue

            for work in data.get("results", []):
                work_id   = work.get("id", "")
                title     = work.get("title") or ""
                pub_date  = work.get("publication_date") or ""
                citations = work.get("cited_by_count", 0)
                authors   = [a.get("author", {}).get("display_name", "") for a in work.get("authorships", [])[:4]]
                venue     = (work.get("primary_location") or {}).get("source", {})
                venue_name = (venue or {}).get("display_name", "") if venue else ""

                # Reconstruct abstract from inverted index
                inv = work.get("abstract_inverted_index") or {}
                abstract = _invert_abstract(inv)[:500]

                if work_id in seen or not title:
                    continue
                seen.add(work_id)

                text = (
                    f"[OpenAlex Research] {title}\n"
                    f"Concept: {label}. Authors: {', '.join(a for a in authors if a)}.\n"
                    f"Venue: {venue_name}. Citations: {citations}.\n"
                    f"Abstract: {abstract}"
                )
                results.append(BaseRawModel(
                    text       = text,
                    source_url = work_id,
                    domain     = "technology",
                    title      = title,
                    published  = pub_date,
                    tags       = ["openalex", "research", label.lower().split()[0]],
                ))

            time.sleep(0.3)

        # India-specific keyword search
        for query in INDIA_QUERIES:
            try:
                resp = requests.get(BASE_URL, params={
                    "search":   query,
                    "filter":   f"from_publication_date:{since}",
                    "per-page": max_per_topic,
                    "select":   "id,title,publication_date,cited_by_count",
                    "mailto":   EMAIL,
                }, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                continue

            for work in data.get("results", []):
                work_id  = work.get("id", "")
                title    = work.get("title") or ""
                pub_date = work.get("publication_date") or ""
                if work_id in seen or not title:
                    continue
                seen.add(work_id)
                results.append(BaseRawModel(
                    text       = f"[OpenAlex India Research] {title}",
                    source_url = work_id,
                    domain     = "technology",
                    title      = title,
                    published  = pub_date,
                    tags       = ["openalex", "india", "research"] + query.lower().split()[:3],
                ))

        return results


def _invert_abstract(inv: dict) -> str:
    """Reconstruct text from OpenAlex inverted abstract index."""
    if not inv:
        return ""
    pos_word: dict = {}
    for word, positions in inv.items():
        for pos in positions:
            pos_word[pos] = word
    return " ".join(pos_word[i] for i in sorted(pos_word))
