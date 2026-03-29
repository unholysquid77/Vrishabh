"""
ACLEDIngestor — Armed Conflict Location & Event Data.
Uses OAuth2 Bearer token flow (POST to /oauth/token, then Bearer auth).
Requires ACLED_EMAIL + ACLED_PASSWORD env vars (free registration at acleddata.com).
Gracefully returns empty if credentials absent or token fetch fails.
"""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import List, Optional

import requests

from global_graph.domains.base_raw_model import BaseRawModel

TOKEN_URL = "https://acleddata.com/oauth/token"
BASE_URL  = "https://acleddata.com/api/acled/read"

COUNTRIES = [
    "India", "Pakistan", "China", "Bangladesh", "Sri Lanka",
    "Myanmar", "Nepal", "Afghanistan", "Iran", "Israel",
    "Ukraine", "Russia", "Sudan", "Ethiopia", "Yemen",
    "Syria", "Somalia", "Mali", "Niger", "Democratic Republic of Congo",
]


class ACLEDIngestor:

    def __init__(self, email: str = "", password: str = ""):
        self._email    = email
        self._password = password
        self._token: Optional[str] = None

    def _get_token(self) -> Optional[str]:
        if self._token:
            return self._token
        if not self._email or not self._password:
            return None
        try:
            resp = requests.post(
                TOKEN_URL,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "username":   self._email,
                    "password":   self._password,
                    "grant_type": "password",
                    "client_id":  "acled",
                },
                timeout=20,
            )
            resp.raise_for_status()
            self._token = resp.json()["access_token"]
            print(f"[ACLED] Token obtained OK")
            return self._token
        except Exception as e:
            print(f"[ACLED] Auth failed: {e}")
            return None

    def fetch(self, limit: int = 100) -> List[BaseRawModel]:
        if not self._email or not self._password:
            print("[ACLED] No credentials — skipping")
            return []

        token = self._get_token()
        if not token:
            return []

        since = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")
        # ACLED multi-country filter syntax
        country_filter = ":OR:country=".join(COUNTRIES)

        try:
            resp = requests.get(
                BASE_URL,
                params={
                    "_format":          "json",
                    "country":          country_filter,
                    "event_date":       since,
                    "event_date_where": ">=",
                    "limit":            limit,
                    "fields": (
                        "event_id_cnty|event_date|event_type|sub_event_type|"
                        "actor1|actor2|country|admin1|location|fatalities|notes|source"
                    ),
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type":  "application/json",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[ACLED] Fetch error: {e}")
            return []

        if data.get("status") != 200:
            print(f"[ACLED] API error: {data.get('error', 'unknown')}")
            return []

        results: List[BaseRawModel] = []
        for ev in data.get("data", []):
            actor1    = ev.get("actor1", "Unknown")
            actor2    = ev.get("actor2", "")
            etype     = ev.get("event_type", "")
            sub_etype = ev.get("sub_event_type", "")
            country   = ev.get("country", "")
            location  = ev.get("location", "")
            admin1    = ev.get("admin1", "")
            date      = ev.get("event_date", "")
            fatalities = ev.get("fatalities", 0)
            notes     = ev.get("notes", "")[:400]

            loc_str = ", ".join(filter(None, [location, admin1, country]))
            actors  = f"{actor1} and {actor2}" if actor2 else actor1
            text = (
                f"[ACLED] {sub_etype or etype} involving {actors} in {loc_str} on {date}. "
                f"Fatalities: {fatalities}. {notes}"
            )
            results.append(BaseRawModel(
                text       = text,
                source_url = f"https://acleddata.com/data/{ev.get('event_id_cnty', '')}",
                domain     = "geopolitics",
                title      = f"ACLED: {sub_etype or etype} – {loc_str}",
                published  = date,
                tags       = ["ACLED", "conflict", country.lower(), etype.lower()],
            ))

        print(f"[ACLED] Fetched {len(results)} conflict events")
        return results
