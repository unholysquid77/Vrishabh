"""
SIPRIIngestor — Stockholm International Peace Research Institute arms transfer data.
Uses seed data on major arms relationships + ReliefWeb SIPRI reports.
No API key required.
"""

from __future__ import annotations
from datetime import datetime
from typing import List

import requests

from global_graph.domains.base_raw_model import BaseRawModel

# Curated arms transfer relationships (supplier → recipient, period, system)
ARMS_SEED = [
    ("Russia",        "India",        "2019-2024", "S-400 air defence system, MiG-29, Su-30MKI"),
    ("France",        "India",        "2016-2024", "Rafale fighter jets, submarines (Scorpène)"),
    ("United States", "India",        "2020-2024", "P-8I patrol aircraft, Apache helicopters, C-130J"),
    ("Israel",        "India",        "2018-2024", "Heron UAVs, Barak missiles, Spyder air defence"),
    ("China",         "Pakistan",     "2015-2024", "J-10CE fighters, HQ-9 air defence, Type 054A frigates"),
    ("United States", "Taiwan",       "2022-2024", "F-16 upgrades, HIMARS, anti-ship missiles"),
    ("Russia",        "China",        "2015-2023", "Su-35 fighters, S-400, aircraft engines"),
    ("United States", "Saudi Arabia", "2017-2024", "F-15SA, THAAD, munitions packages"),
    ("Germany",       "Ukraine",      "2022-2024", "Leopard 2 tanks, Gepard SPAAG, IRIS-T"),
    ("United States", "Ukraine",      "2022-2024", "HIMARS, Patriot, M1 Abrams, Javelin ATGMs"),
    ("United States", "Israel",       "2023-2024", "Joint Direct Attack Munitions, F-35, Arrow 3"),
    ("Russia",        "Iran",         "2022-2024", "Shahed-136 drones (licence), air defence"),
    ("North Korea",   "Russia",       "2023-2024", "Artillery shells, Hwasong-11 ballistic missiles"),
    ("France",        "Greece",       "2021-2024", "Rafale fighters, FDI frigates"),
    ("China",         "UAE",          "2020-2024", "Wing Loong II UAVs, CH-4 drones"),
]

RELIEFWEB_URL = "https://api.reliefweb.int/v2/reports"


class SIPRIIngestor:

    def fetch(self) -> List[BaseRawModel]:
        results: List[BaseRawModel] = []

        # 1. Seed arms relationships
        for supplier, recipient, period, systems in ARMS_SEED:
            text = (
                f"[SIPRI Arms Transfer] {supplier} → {recipient} ({period}): {systems}. "
                f"Source: Stockholm International Peace Research Institute (SIPRI) Arms Transfers Database."
            )
            results.append(BaseRawModel(
                text       = text,
                source_url = "https://www.sipri.org/databases/armstransfers",
                domain     = "geopolitics",
                title      = f"Arms Transfer: {supplier} to {recipient}",
                published  = f"{period.split('-')[1]}-01-01T00:00:00" if "-" in period else datetime.utcnow().isoformat(),
                tags       = ["SIPRI", "arms", "military", supplier.lower(), recipient.lower()],
            ))

        # 2. Pull SIPRI reports mirrored on ReliefWeb
        try:
            resp = requests.post(RELIEFWEB_URL, json={
                "filter": {"field": "source.name", "value": "SIPRI"},
                "fields": {"include": ["title", "body", "date.created", "url"]},
                "sort":   ["date.created:desc"],
                "limit":  10,
            }, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("data", []):
                f = item.get("fields", {})
                title = f.get("title", "")
                body  = (f.get("body") or "")[:600]
                url   = f.get("url", "https://www.sipri.org")
                date  = (f.get("date") or {}).get("created", "")
                if title:
                    results.append(BaseRawModel(
                        text       = f"[SIPRI Report] {title}\n{body}",
                        source_url = url,
                        domain     = "geopolitics",
                        title      = title,
                        published  = date,
                        tags       = ["SIPRI", "defence", "military", "arms"],
                    ))
        except Exception as e:
            print(f"[SIPRI] ReliefWeb fetch failed: {e}")

        return results
