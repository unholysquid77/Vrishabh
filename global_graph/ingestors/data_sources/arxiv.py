"""
ArXivIngestor — fetches recent research preprints from ArXiv across tech-relevant categories.
Free, no API key.
"""

from __future__ import annotations
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List

import requests

from global_graph.domains.base_raw_model import BaseRawModel

BASE_URL = "http://export.arxiv.org/api/query"
NS       = "{http://www.w3.org/2005/Atom}"

SEARCH_QUERIES = [
    # AI / ML
    ("cs.AI", "large language model transformer reinforcement learning"),
    ("cs.LG", "deep learning neural network optimization"),
    # Semiconductors / hardware
    ("cs.AR", "semiconductor chip design VLSI FPGA"),
    # Cybersecurity
    ("cs.CR", "cybersecurity vulnerability exploit zero-day"),
    # Quantum
    ("quant-ph", "quantum computing error correction qubit"),
    # Robotics
    ("cs.RO", "robotics autonomous drone swarm"),
    # India-specific research
    ("", "ISRO satellite India space programme"),
    ("", "DRDO India defence technology missile"),
    ("", "India semiconductor fab chip manufacturing"),
    # Biotech
    ("q-bio.GN", "CRISPR gene editing genome"),
    # Space
    ("astro-ph.IM", "satellite Earth observation remote sensing"),
]


class ArXivIngestor:

    def fetch(self, max_per_query: int = 3) -> List[BaseRawModel]:
        results: List[BaseRawModel] = []
        seen: set = set()
        since = (datetime.utcnow() - timedelta(days=30)).strftime("%Y%m%d")

        for cat, query in SEARCH_QUERIES:
            search = f"cat:{cat} AND all:{query}" if cat else f"all:{query}"
            try:
                resp = requests.get(BASE_URL, params={
                    "search_query": search,
                    "start":        0,
                    "max_results":  max_per_query,
                    "sortBy":       "submittedDate",
                    "sortOrder":    "descending",
                }, timeout=20)
                resp.raise_for_status()
                root = ET.fromstring(resp.text)
            except Exception as e:
                print(f"[ArXiv] query '{query}' failed: {e}")
                time.sleep(1)
                continue

            for entry in root.findall(f"{NS}entry"):
                arxiv_id = (entry.findtext(f"{NS}id") or "").strip()
                title    = (entry.findtext(f"{NS}title") or "").strip().replace("\n", " ")
                summary  = (entry.findtext(f"{NS}summary") or "").strip().replace("\n", " ")[:600]
                published = entry.findtext(f"{NS}published") or ""
                authors  = [a.findtext(f"{NS}name") or "" for a in entry.findall(f"{NS}author")]

                if arxiv_id in seen:
                    continue
                seen.add(arxiv_id)

                text = (
                    f"[ArXiv Research] {title}\n"
                    f"Authors: {', '.join(authors[:5])}.\n"
                    f"Abstract: {summary}"
                )
                results.append(BaseRawModel(
                    text       = text,
                    source_url = arxiv_id,
                    domain     = "technology",
                    title      = title,
                    published  = published,
                    tags       = ["arxiv", "research", cat or "general"] + query.lower().split()[:4],
                ))

            time.sleep(0.5)

        return results
