"""
OpenMeteoIngestor — fetches recent weather anomalies for key cities.
Free, no API key.
"""

from __future__ import annotations
from datetime import datetime, timedelta
from typing import List

import requests

from global_graph.domains.base_raw_model import BaseRawModel

BASE_URL = "https://api.open-meteo.com/v1/forecast"

# Key cities representative of major climate regions
LOCATIONS = [
    ("New Delhi",     28.6139, 77.2090),
    ("Mumbai",        19.0760, 72.8777),
    ("Beijing",       39.9042, 116.4074),
    ("London",        51.5074, -0.1278),
    ("New York",      40.7128, -74.0060),
    ("Lagos",          6.5244,  3.3792),
    ("São Paulo",     -23.5505, -46.6333),
    ("Sydney",        -33.8688, 151.2093),
    ("Dubai",         25.2048, 55.2708),
    ("Moscow",        55.7558, 37.6173),
]


class OpenMeteoIngestor:

    def fetch(self) -> List[BaseRawModel]:
        results: List[BaseRawModel] = []
        today = datetime.utcnow().date()
        start = (today - timedelta(days=7)).isoformat()
        end   = today.isoformat()

        for city, lat, lon in LOCATIONS:
            try:
                resp = requests.get(BASE_URL, params={
                    "latitude":  lat,
                    "longitude": lon,
                    "daily":     "temperature_2m_max,precipitation_sum",
                    "start_date": start,
                    "end_date":   end,
                    "timezone":  "UTC",
                }, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"[OpenMeteo] {city} failed: {e}")
                continue

            daily = data.get("daily", {})
            dates  = daily.get("time", [])
            temps  = daily.get("temperature_2m_max", [])
            precip = daily.get("precipitation_sum", [])

            if not dates:
                continue

            # Summarise the 7-day window into one raw model
            valid_temps  = [t for t in temps  if t is not None]
            valid_precip = [p for p in precip if p is not None]
            avg_temp  = round(sum(valid_temps)  / len(valid_temps),  1) if valid_temps  else "N/A"
            avg_precip = round(sum(valid_precip) / len(valid_precip), 1) if valid_precip else "N/A"
            max_temp  = max(valid_temps)  if valid_temps  else "N/A"

            text = (
                f"Weather data for {city} ({start} to {end}): "
                f"avg max temperature {avg_temp}°C, peak {max_temp}°C, "
                f"avg daily precipitation {avg_precip}mm. "
                f"Coordinates: {lat}N, {lon}E."
            )
            results.append(BaseRawModel(
                text       = text,
                source_url = f"https://open-meteo.com/city/{city.lower().replace(' ','-')}",
                domain     = "climate",
                title      = f"Weather Report: {city} {start}/{end}",
                published  = datetime.utcnow().isoformat(),
                tags       = ["weather", "temperature", "precipitation", city.lower()],
            ))

        return results
