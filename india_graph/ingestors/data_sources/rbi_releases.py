"""
RBIReleasesIngestor — fetches press releases and monetary policy decisions from RBI.
Scrapes the RBI press release RSS feeds. Free, no API key.
RBI feeds often have encoding quirks — we strip invalid XML chars before parsing.
"""

from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from typing import List

import requests

from global_graph.domains.base_raw_model import BaseRawModel

RBI_FEEDS = [
    ("https://rbi.org.in/scripts/rss.aspx?Id=3",  "RBI Press Release"),
    ("https://rbi.org.in/scripts/rss.aspx?Id=17", "RBI Monetary Policy"),
]

# Remove XML-illegal control characters (common in Indian govt feeds)
_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitise(raw_bytes: bytes) -> bytes:
    """Strip control chars that break ElementTree parsing."""
    text = raw_bytes.decode("utf-8", errors="replace")
    text = _INVALID_XML.sub("", text)
    return text.encode("utf-8")


class RBIReleasesIngestor:

    def fetch(self, max_per_feed: int = 10) -> List[BaseRawModel]:
        results: List[BaseRawModel] = []
        seen: set = set()

        for url, source_label in RBI_FEEDS:
            try:
                resp = requests.get(
                    url, timeout=15,
                    headers={"User-Agent": "Mozilla/5.0 Vrishabh/1.0"},
                )
                resp.raise_for_status()
                clean  = _sanitise(resp.content)
                root   = ET.fromstring(clean)
            except Exception as e:
                print(f"[RBI] '{source_label}' feed failed: {e}")
                continue

            items = root.findall(".//item")[:max_per_feed]
            fetched = 0
            for item in items:
                title   = (item.findtext("title")       or "").strip()
                link    = (item.findtext("link")         or "").strip()
                pubdate = (item.findtext("pubDate")      or "").strip()
                desc    = (item.findtext("description")  or "").strip()[:500]

                if link in seen:
                    continue
                seen.add(link)
                fetched += 1

                results.append(BaseRawModel(
                    text       = f"[{source_label}] {title}\n{desc}",
                    source_url = link or url,
                    domain     = "india_policy",
                    title      = title,
                    published  = pubdate,
                    tags       = ["RBI", "india", "monetary_policy", "central_bank"],
                ))

            print(f"[RBI] '{source_label}' → {fetched} releases")

        return results
