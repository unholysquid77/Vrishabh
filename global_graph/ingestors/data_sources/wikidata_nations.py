"""
WikidataNationsIngestor — pulls sovereign nations, heads of state, and alliances
from the Wikidata public SPARQL endpoint.
Free, no API key.
"""

from __future__ import annotations
from datetime import datetime
from typing import List

import requests

from global_graph.domains.base_raw_model import BaseRawModel

SPARQL_URL = "https://query.wikidata.org/sparql"
HEADERS    = {"Accept": "application/sparql-results+json",
               "User-Agent": "Vrishabh/1.0 (financial intelligence graph)"}

# Wikidata SPARQL for sovereign countries with population + region
NATIONS_QUERY = """
SELECT ?countryLabel ?isoCode ?capitalLabel ?regionLabel ?population WHERE {
  ?country wdt:P31 wd:Q3624078 .              # sovereign state
  OPTIONAL { ?country wdt:P297 ?isoCode }      # ISO 3166-1 alpha-2
  OPTIONAL { ?country wdt:P36  ?capital }
  OPTIONAL { ?country wdt:P361 ?region }
  OPTIONAL { ?country wdt:P1082 ?population }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
}
ORDER BY DESC(?population)
LIMIT 80
"""

# Active international alliances
ALLIANCES_QUERY = """
SELECT ?allianceLabel ?memberLabel WHERE {
  VALUES ?alliance {
    wd:Q7184       # NATO
    wd:Q41438      # SCO
    wd:Q40864      # BRICS
    wd:Q82828      # Quad
    wd:Q458        # EU
    wd:Q7768       # ASEAN
    wd:Q8908       # African Union
    wd:Q5086       # G20
    wd:Q65250      # AUKUS
  }
  ?alliance wdt:P527 ?member .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" }
}
"""


class WikidataNationsIngestor:

    def fetch(self) -> List[BaseRawModel]:
        results: List[BaseRawModel] = []
        results += self._fetch_nations()
        results += self._fetch_alliances()
        return results

    def _fetch_nations(self) -> List[BaseRawModel]:
        try:
            resp = requests.get(SPARQL_URL, params={"query": NATIONS_QUERY, "format": "json"},
                                headers=HEADERS, timeout=30)
            resp.raise_for_status()
            bindings = resp.json().get("results", {}).get("bindings", [])
        except Exception as e:
            print(f"[Wikidata] nations query failed: {e}")
            return []

        rows: List[BaseRawModel] = []
        for b in bindings:
            name    = b.get("countryLabel", {}).get("value", "")
            iso     = b.get("isoCode",      {}).get("value", "")
            capital = b.get("capitalLabel", {}).get("value", "")
            region  = b.get("regionLabel",  {}).get("value", "")
            pop     = b.get("population",   {}).get("value", "")
            if not name or name.startswith("Q"):
                continue
            text = (
                f"[Wikidata Nation] {name} (ISO: {iso}). "
                f"Capital: {capital}. Region: {region}. "
                f"Population: {pop}."
            )
            rows.append(BaseRawModel(
                text       = text,
                source_url = f"https://www.wikidata.org/wiki/Special:Search/{iso}",
                domain     = "geopolitics",
                title      = f"Nation: {name}",
                published  = datetime.utcnow().isoformat(),
                tags       = ["wikidata", "nation", iso.lower(), region.lower()[:20]],
            ))
        return rows

    def _fetch_alliances(self) -> List[BaseRawModel]:
        try:
            resp = requests.get(SPARQL_URL, params={"query": ALLIANCES_QUERY, "format": "json"},
                                headers=HEADERS, timeout=30)
            resp.raise_for_status()
            bindings = resp.json().get("results", {}).get("bindings", [])
        except Exception as e:
            print(f"[Wikidata] alliances query failed: {e}")
            return []

        # Group by alliance name
        alliances: dict = {}
        for b in bindings:
            alliance = b.get("allianceLabel", {}).get("value", "")
            member   = b.get("memberLabel",   {}).get("value", "")
            if not alliance or alliance.startswith("Q"):
                continue
            alliances.setdefault(alliance, []).append(member)

        rows: List[BaseRawModel] = []
        for alliance, members in alliances.items():
            members_str = ", ".join(m for m in members if not m.startswith("Q"))
            text = (
                f"[Wikidata Alliance] {alliance} members: {members_str}. "
                f"Source: Wikidata knowledge base."
            )
            rows.append(BaseRawModel(
                text       = text,
                source_url = "https://www.wikidata.org",
                domain     = "geopolitics",
                title      = f"Alliance: {alliance}",
                published  = datetime.utcnow().isoformat(),
                tags       = ["wikidata", "alliance", alliance.lower()[:20]],
            ))
        return rows
