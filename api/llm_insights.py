"""
LLM Quick Insights Pipeline — 2-call approach.

Call 1  (Planner):   Given tools + stock list, emit ALL data-retrieval
                     calls needed as a single JSON object.
Execute calls:       Run each call, gather results (including live websearch).
Call 2  (Analyst):   Given all gathered data, reason over it and produce
                     one structured insight card per stock.

Designed to be much faster than the full RLM loop while still being
grounded in live market data.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Optional

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

# ──────────────────────────────────────────────────────────────────
# TOOL REGISTRY
# Each tool is a dict: {name, description, fn: callable}
# ──────────────────────────────────────────────────────────────────

def _build_tool_registry(ta, bsnm, radar) -> Dict[str, dict]:
    """Build the lightweight tool registry for the LLM pipeline."""
    try:
        from api.websearch import websearch  # type: ignore  (when imported from root)
    except ImportError:
        from websearch import websearch  # type: ignore  (when run from api/)

    def _ta_tool(ticker: str) -> dict:
        try:
            sig = ta.analyse(ticker)
            return sig.to_dict() if sig else {"error": f"No TA data for {ticker}"}
        except Exception as e:
            return {"error": str(e)}

    def _sentiment_tool(ticker: str) -> dict:
        try:
            result = bsnm.analyse(ticker)
            return result if isinstance(result, dict) else vars(result)
        except Exception as e:
            return {"error": str(e)}

    def _radar_tool(ticker: str) -> dict:
        try:
            alerts = radar.scan([ticker])
            return {"alerts": [a.__dict__ if hasattr(a, "__dict__") else a for a in (alerts or [])]}
        except Exception as e:
            return {"error": str(e)}

    def _websearch_tool(ticker: str, query: str = "") -> dict:
        q = query or f"{ticker} NSE stock news analysis India"
        tags = [ticker, f"{ticker} NSE", "India stock market"] + (
            [t.strip() for t in query.split() if len(t.strip()) > 3] if query else []
        )
        return websearch(tags[:8], q)

    return {
        "get_technical_signals": {
            "description": "Get TA score, regime, masala scores, patterns for a ticker.",
            "args": {"ticker": "NSE ticker symbol (e.g. RELIANCE)"},
            "fn": _ta_tool,
        },
        "get_news_sentiment": {
            "description": "Get news sentiment score and recent headlines for a ticker.",
            "args": {"ticker": "NSE ticker symbol"},
            "fn": _sentiment_tool,
        },
        "get_radar_alerts": {
            "description": "Get opportunity radar alerts for a ticker.",
            "args": {"ticker": "NSE ticker symbol"},
            "fn": _radar_tool,
        },
        "websearch": {
            "description": (
                "Live web search for news and analysis about a ticker. "
                "Returns recent articles + AI-grounded analysis."
            ),
            "args": {
                "ticker": "NSE ticker symbol",
                "query":  "Optional custom search query",
            },
            "fn": _websearch_tool,
        },
    }


# ──────────────────────────────────────────────────────────────────
# PLANNER PROMPT  (Call 1)
# ──────────────────────────────────────────────────────────────────

_PLANNER_SYSTEM = """You are a stock research planner for an Indian retail investor platform.
Given a list of NSE stocks and the available tools, output ALL the data-retrieval
calls that are needed to produce well-grounded investment insights.

RULES:
- For each stock, plan calls to ALL relevant tools.
- Include at least get_technical_signals and websearch for every ticker.
- Be comprehensive — you will not get another chance to request data.
- Output ONLY a valid JSON object in this exact schema, no other text:

{
  "calls": [
    {"tool": "<tool_name>", "args": {"<arg_name>": "<value>"}},
    ...
  ]
}
"""

def _planner_prompt(tickers: List[str], tool_specs: str) -> str:
    return (
        f"Stocks to analyse: {', '.join(tickers)}\n\n"
        f"Available tools:\n{tool_specs}\n\n"
        f"Output the complete list of data calls needed."
    )


# ──────────────────────────────────────────────────────────────────
# ANALYST PROMPT  (Call 2)
# ──────────────────────────────────────────────────────────────────

_ANALYST_SYSTEM = """You are Vrishabh, an AI investment analyst for Indian retail investors.
You have been given live market data, news, and technical analysis for a set of NSE stocks.
Your job is to synthesise all this data into clear, actionable investment insights.

RULES:
- Produce EXACTLY ONE insight per stock — no duplicates.
- Be specific: reference actual data from the provided context (prices, TA scores, news).
- Write for a retail investor: plain language, no jargon without explanation.
- suggested_action must be one of: BUY, SELL, HOLD.
- Output ONLY a valid JSON object, no other text:

{
  "insights": [
    {
      "ticker": "TICKER",
      "action": "BUY" | "SELL" | "HOLD",
      "summary": "One concise sentence summarising the key driver today.",
      "india_context": "India macro / sector / policy context relevant to this stock.",
      "global_context": "Global forces (supply chain, FII, geopolitics) if relevant.",
      "market_signals": "TA regime, score, key pattern detected.",
      "key_risks": "Top 1-2 risks the investor must watch.",
      "suggestion": "Specific, actionable advice for a retail investor right now."
    }
  ]
}
"""

def _analyst_prompt(tickers: List[str], gathered: Dict[str, Any]) -> str:
    parts = [f"Stocks: {', '.join(tickers)}\n\n=== GATHERED DATA ===\n"]
    for ticker, data in gathered.items():
        parts.append(f"\n--- {ticker} ---\n{json.dumps(data, ensure_ascii=False, default=str)[:4000]}")
    return "\n".join(parts)


# ──────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────

def _extract_json(raw: str) -> dict:
    """Extract the first JSON object from raw text, tolerating markdown fences."""
    clean = re.sub(r"```(?:json)?\s*", "", raw).strip()
    m = re.search(r"\{[\s\S]*\}", clean)
    if not m:
        raise ValueError(f"No JSON object found in:\n{raw[:300]}")
    candidate = m.group(0)
    candidate = candidate[: candidate.rfind("}") + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return json.loads(re.sub(r"[\x00-\x1f\x7f]", "", candidate))


def _llm_call(system: str, user: str, model: str = "gpt-4o-mini") -> str:
    """Single OpenAI chat completion."""
    from openai import OpenAI  # type: ignore
    client = OpenAI(api_key=OPENAI_API_KEY)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=0.2,
        max_tokens=4096,
    )
    return resp.choices[0].message.content or ""


# ──────────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ──────────────────────────────────────────────────────────────────

def run_llm_insights(
    tickers: List[str],
    ta,
    bsnm,
    radar,
    sig_map: Optional[Dict] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Two-call LLM insights pipeline.

    Args:
        tickers:     List of NSE tickers to analyse.
        ta:          SuvarnTAClient instance.
        bsnm:        SuvarnBSNMClient instance.
        radar:       OpportunityRadar instance.
        sig_map:     Pre-computed TA signal dicts {ticker: sig.to_dict()} (optional).
        progress_cb: Optional callback for streaming progress text.

    Returns:
        {"insights": [...]}  — same schema as the RLM /insights endpoint.
    """

    def _log(msg: str):
        print(f"[LLMInsights] {msg}")
        if progress_cb:
            progress_cb(msg)

    registry = _build_tool_registry(ta, bsnm, radar)

    # Build tool spec string for the planner
    tool_specs = "\n".join(
        f"  {name}({', '.join(f'{k}: {v}' for k, v in spec['args'].items())}) "
        f"— {spec['description']}"
        for name, spec in registry.items()
    )

    # ── CALL 1: Planner ───────────────────────────────────
    _log(f"Planning data calls for {len(tickers)} stocks…")
    planner_out = _llm_call(
        _PLANNER_SYSTEM,
        _planner_prompt(tickers, tool_specs),
        model="gpt-4o-mini",
    )

    try:
        plan = _extract_json(planner_out)
        calls: List[dict] = plan.get("calls", [])
    except Exception as e:
        _log(f"Planner JSON parse error: {e} — building default call set")
        calls = [
            {"tool": t, "args": {"ticker": tk}}
            for tk in tickers
            for t in ("get_technical_signals", "get_news_sentiment", "websearch")
        ]

    _log(f"Planner scheduled {len(calls)} data calls.")

    # ── Execute calls ─────────────────────────────────────
    # Group by ticker for prettier progress output
    gathered: Dict[str, Dict] = {t: {} for t in tickers}
    completed = 0

    for call in calls:
        tool_name = call.get("tool", "")
        args      = call.get("args", {})
        spec      = registry.get(tool_name)
        if not spec:
            continue

        ticker_hint = args.get("ticker", "?").upper()
        _log(f"  [{completed+1}/{len(calls)}] {tool_name}({ticker_hint})…")
        try:
            result = spec["fn"](**args)
        except Exception as e:
            result = {"error": str(e)}

        # Store under the ticker this call is for
        canonical = ticker_hint.replace(".NS", "")
        if canonical in gathered:
            gathered[canonical][tool_name] = result
        else:
            gathered[canonical] = {tool_name: result}

        completed += 1

    # Inject pre-computed TA signal data if available
    if sig_map:
        for ticker, sig_dict in sig_map.items():
            if ticker in gathered:
                gathered[ticker].setdefault("pre_computed_ta", sig_dict)

    # ── CALL 2: Analyst ───────────────────────────────────
    _log("Synthesising insights…")
    analyst_out = _llm_call(
        _ANALYST_SYSTEM,
        _analyst_prompt(tickers, gathered),
        model="gpt-4o",   # Use the smarter model for final reasoning
    )

    try:
        parsed = _extract_json(analyst_out)
    except Exception as e:
        raise RuntimeError(f"Analyst JSON parse error: {e}\nRaw:\n{analyst_out[:600]}")

    # Dedup — keep only one insight per ticker (last wins if LLM repeated)
    seen_tickers: set = set()
    deduped = []
    for ins in parsed.get("insights", []):
        t = (ins.get("ticker") or "").upper()
        if t and t not in seen_tickers:
            seen_tickers.add(t)
            deduped.append(ins)

    # Enrich with numeric TA data
    if sig_map:
        for ins in deduped:
            t = ins.get("ticker", "")
            sd = sig_map.get(t, {})
            ins.setdefault("pct_change", sd.get("pct_change"))
            ins.setdefault("last_close", sd.get("last_close"))
            ins.setdefault("score",      sd.get("score"))
            ins.setdefault("action",     sd.get("suggested_action", "HOLD"))

    _log(f"Done — {len(deduped)} insight cards generated.")
    return {"insights": deduped}
