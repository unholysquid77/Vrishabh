"""
SECEdgarIngestor — fetches recent SEC filings via EDGAR RSS feeds.
Free, no API key. Uses the EDGAR full-text RSS for 8-K and 13F-HR.

Note: Paqshi uses the paid sec-api.io package. We use the free EDGAR
Atom/RSS feeds instead which have no auth requirement.
"""

from __future__ import annotations
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List

import requests

from global_graph.domains.base_raw_model import BaseRawModel

HEADERS  = {"User-Agent": "Vrishabh/1.0 financial-intelligence@example.com",
             "Accept-Encoding": "gzip, deflate"}

# EDGAR RSS feeds for recent filings (last 40 per form type)
EDGAR_FEEDS = [
    ("8-K",    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&dateb=&owner=include&count=40&search_text=&output=atom"),
    ("13F-HR", "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=13F-HR&dateb=&owner=include&count=40&search_text=&output=atom"),
]

ATOM_NS = "{http://www.w3.org/2005/Atom}"


class SECEdgarIngestor:

    def fetch(self) -> List[BaseRawModel]:
        results: List[BaseRawModel] = []
        for form_type, url in EDGAR_FEEDS:
            results += self._fetch_feed(form_type, url)
        print(f"[SEC EDGAR] Fetched {len(results)} filings")
        return results

    def _fetch_feed(self, form_type: str, url: str) -> List[BaseRawModel]:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as e:
            print(f"[SEC EDGAR] {form_type} feed failed: {e}")
            return []

        rows: List[BaseRawModel] = []
        for entry in root.findall(f"{ATOM_NS}entry"):
            title    = (entry.findtext(f"{ATOM_NS}title") or "").strip()
            link_el  = entry.find(f"{ATOM_NS}link")
            link     = (link_el.get("href") if link_el is not None else "") or ""
            updated  = (entry.findtext(f"{ATOM_NS}updated") or "").strip()
            summary  = (entry.findtext(f"{ATOM_NS}summary") or "").strip()[:400]
            cat_el   = entry.find(f"{ATOM_NS}category")
            company  = (cat_el.get("label") if cat_el is not None else "") or title

            if not title:
                continue

            text = (
                f"[SEC EDGAR {form_type}] {title}\n"
                f"Filed: {updated}. Company: {company}.\n"
                f"{summary}"
            )
            rows.append(BaseRawModel(
                text       = text,
                source_url = link or url,
                domain     = "corporate",
                title      = title,
                published  = updated,
                tags       = ["SEC", form_type, "filing", "corporate"],
            ))

        print(f"[SEC EDGAR] {form_type}: {len(rows)} filings from RSS")
        return rows
