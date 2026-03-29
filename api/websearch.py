"""
VrishabWebSearch — mirrors Paqshi's websearch facade.

Two-part search:
  1. NewsData API  (NEWSDATA_API_KEY env var)  — batched tag queries
  2. OpenAI web_search_preview tool            — live grounded search

Falls back gracefully when keys are missing.
"""

from __future__ import annotations

import os
from typing import List


NEWSDATA_API_KEY: str = os.getenv("NEWSDATA_API_KEY", "")
OPENAI_API_KEY:   str = os.getenv("OPENAI_API_KEY",   "")


def websearch(tags: List[str], prompt: str) -> dict:
    """
    Search for news + web analysis given a list of tags and a research question.

    Returns:
        {
          "news":     [ {title, source, date, summary, url}, ... ],
          "analysis": "...",
          "sources":  [ {title, url}, ... ]
        }
    """
    output: dict = {"news": [], "analysis": "", "sources": []}

    # ──────────────────────────────────────────────────────────
    # PART 1: NewsData API — batched tag queries
    # ──────────────────────────────────────────────────────────
    if NEWSDATA_API_KEY:
        try:
            from newsdataapi import NewsDataApiClient  # type: ignore
            news_client = NewsDataApiClient(apikey=NEWSDATA_API_KEY)
            BATCH_SIZE = 4
            seen_urls: set = set()

            for i in range(0, len(tags), BATCH_SIZE):
                batch = tags[i : i + BATCH_SIZE]
                query = " OR ".join(batch)
                if len(query) > 100:
                    query = query[:97].rsplit(" ", 1)[0] + "..."
                try:
                    resp = news_client.latest_api(q=query, language="en", page=None)
                    for art in resp.get("results", [])[:5]:
                        url = art.get("link", "")
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            output["news"].append({
                                "title":   art.get("title"),
                                "source":  art.get("source_name"),
                                "date":    art.get("pubDate"),
                                "summary": art.get("description"),
                                "url":     url,
                            })
                except Exception as e:
                    output["news"].append({"error": f"newsdata batch '{query}': {e}"})

        except ImportError:
            output["news"].append({"error": "newsdataapi package not installed"})

    # ──────────────────────────────────────────────────────────
    # PART 2: OpenAI web_search_preview (live grounded search)
    # ──────────────────────────────────────────────────────────
    if OPENAI_API_KEY:
        try:
            from openai import OpenAI  # type: ignore
            client = OpenAI(api_key=OPENAI_API_KEY)

            analysis_prompt = (
                f"You are a financial OSINT analyst.\n"
                f"Search the web for current, factual information.\n\n"
                f"Keywords: {', '.join(tags)}\n\n"
                f"Question: {prompt}\n\n"
                f"Structure your response as:\n"
                f"- Key findings (bullet points, include source URLs)\n"
                f"- Analytical summary (2-3 sentences with India-market context)\n\n"
                f"Be concise, factual, and prioritise recent sources."
            )

            resp = client.responses.create(
                model="gpt-4o-mini",
                tools=[{"type": "web_search_preview"}],
                input=analysis_prompt,
            )
            output["analysis"] = getattr(resp, "output_text", "") or ""

            for item in getattr(resp, "output", []):
                for ann in getattr(item, "annotations", []) or []:
                    if getattr(ann, "type", "") == "url_citation":
                        output["sources"].append({
                            "title": getattr(ann, "title", ""),
                            "url":   getattr(ann, "url",   ""),
                        })

        except Exception as e:
            output["analysis"] = f"[web search error: {e}]"

    return output
