"""
Radar Compressor — collapses multiple alerts per ticker into one synthesized card.

Categories:
  technical   → TA_BSNM_CONFLUENCE, TA_BSNM_BEAR_CONFLUENCE, CHART_PATTERN, REGIME_ALERT
  news_market → STRONG_NEWS, INSIDER_TRADE, CORPORATE_EVENT

Pipeline:
  1. Group raw alert dicts by (ticker, category)
  2. Single-alert groups → used directly
  3. Multi-alert groups  → gpt-4o-mini synthesises into one unified card
  4. Return {"technical": [...], "news_market": [...]} sorted by strength desc
"""

from __future__ import annotations

import json
from typing import Dict, List, Tuple

try:
    from openai import OpenAI as _OpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False

_TECHNICAL_TYPES = {
    "TA_BSNM_CONFLUENCE",
    "TA_BSNM_BEAR_CONFLUENCE",
    "CHART_PATTERN",
    "REGIME_ALERT",
}
_NEWS_TYPES = {
    "STRONG_NEWS",
    "INSIDER_TRADE",
    "CORPORATE_EVENT",
}

_COMPRESS_SYSTEM = (
    "You are a concise market analyst for Indian equities. "
    "You are given several overlapping radar alerts for the same stock and category. "
    "Synthesise them into ONE unified opportunity description. "
    "Return ONLY a JSON object with keys:\n"
    "  title            (string, ≤12 words)\n"
    "  body             (string, 1-2 sentences, plain English)\n"
    "  suggested_action (BUY | SELL | WATCH | HOLD)\n"
    "  direction        (bullish | bearish | neutral)\n"
    "  strength         (float 0-1)\n"
    "No other keys. No prose outside the JSON."
)


def _categorize(alert_type: str) -> str:
    if alert_type in _TECHNICAL_TYPES:
        return "technical"
    return "news_market"


def _alert_to_card(alert: dict, category: str) -> dict:
    return {
        "ticker":           alert["ticker"],
        "category":         category,
        "title":            alert["title"],
        "body":             alert["body"],
        "suggested_action": alert.get("suggested_action", "WATCH"),
        "direction":        alert.get("direction", "neutral"),
        "strength":         alert.get("strength", 0.0),
        "evidence":         alert.get("evidence", []),
        "alert_count":      1,
    }


def _compress_group(
    ticker: str,
    category: str,
    alerts: List[dict],
    openai_key: str,
) -> dict:
    """Merge 2+ alerts for (ticker, category) via gpt-4o-mini."""
    best_strength = max(a.get("strength", 0) for a in alerts)

    if not _HAS_OPENAI or not openai_key:
        best = max(alerts, key=lambda a: a.get("strength", 0))
        card = _alert_to_card(best, category)
        card["alert_count"] = len(alerts)
        card["evidence"]    = [a["title"] for a in alerts]
        return card

    context = "\n".join(
        f"- [{a['alert_type']}] {a['title']}: {a['body']}"
        f" (strength {a.get('strength', 0):.0%}, {a.get('direction','?')}, {a.get('suggested_action','?')})"
        for a in alerts
    )
    prompt = (
        f"Ticker: {ticker}\n"
        f"Category: {category}\n"
        f"Alerts to merge:\n{context}\n\n"
        "Write ONE unified opportunity card as JSON."
    )

    try:
        client = _OpenAI(api_key=openai_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _COMPRESS_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
            max_tokens=220,
        )
        data = json.loads(resp.choices[0].message.content)
        return {
            "ticker":           ticker,
            "category":         category,
            "title":            data.get("title", f"{ticker}: {category.replace('_', ' ').title()} Signal"),
            "body":             data.get("body", ""),
            "suggested_action": data.get("suggested_action", "WATCH"),
            "direction":        data.get("direction", "neutral"),
            "strength":         float(data.get("strength", best_strength)),
            "evidence":         [a["title"] for a in alerts],
            "alert_count":      len(alerts),
        }
    except Exception as e:
        print(f"[RadarCompress] LLM failed for {ticker}/{category}: {e}")
        best = max(alerts, key=lambda a: a.get("strength", 0))
        card = _alert_to_card(best, category)
        card["alert_count"] = len(alerts)
        card["evidence"]    = [a["title"] for a in alerts]
        return card


def compress_alerts(raw_alerts: List[dict], openai_key: str) -> Dict[str, List[dict]]:
    """
    Takes raw alert dicts (from radar.scan() → .to_dict()),
    returns {"technical": [...], "news_market": [...]}.
    One card per ticker per category, merged via mini-LLM when needed.
    """
    # Group by (ticker, category)
    groups: Dict[Tuple[str, str], List[dict]] = {}
    for a in raw_alerts:
        cat = _categorize(a.get("alert_type", ""))
        key = (a["ticker"], cat)
        groups.setdefault(key, []).append(a)

    technical:   List[dict] = []
    news_market: List[dict] = []

    for (ticker, cat), alerts in groups.items():
        if len(alerts) == 1:
            card = _alert_to_card(alerts[0], cat)
        else:
            card = _compress_group(ticker, cat, alerts, openai_key)

        if cat == "technical":
            technical.append(card)
        else:
            news_market.append(card)

    technical.sort(key=lambda c: c["strength"], reverse=True)
    news_market.sort(key=lambda c: c["strength"], reverse=True)

    return {"technical": technical, "news_market": news_market}
