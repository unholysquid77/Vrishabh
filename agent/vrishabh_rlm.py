"""
VrishabRLM — Agentic market chat using the RLM framework.
Architecture mirrors PaqshiRLM but with finance-specific tools
and a portfolio-aware system prompt.
"""

from __future__ import annotations

import json
import os
from typing import Callable, Dict, Optional

from rlm import RLM
from rlm.logger import RLMLogger

from config import OPENAI_API_KEY, LLM_MODEL_MAIN
from graph import GraphRepository
from suvarn_client import SuvarnTAClient as TAEngine, SuvarnBSNMClient as BSNMEngine
from radar.radar import OpportunityRadar
from .tools import build_tools

SYSTEM_PROMPT = """
You are Vrishabh — a sharp, no-nonsense AI equity analyst built for the Indian retail investor.
You think like a sell-side analyst who has studied every BSE filing, every RBI circular,
and every global macro shock that has moved Indian markets in the last decade.

You have access to TWO intelligence knowledge graphs plus live market tools.
Your job is to synthesise all three layers and give a verdict the user can actually act on.

━━━ LAYER 1: INDIA INTELLIGENCE GRAPH ━━━
India-specific business ontology: companies & conglomerates (Tata, Reliance, Adani, HDFC…),
NIFTY sector classification, stock indices, mutual funds, RBI policy decisions, SEBI rules,
Union Budget events, GDP/inflation/IIP/PMI, FDI/FPI flows, corporate events, business groups.

  india_search(query, limit)          → keyword search across all India entities
  india_semantic_search(query, limit) → embedding-based conceptual search
  india_explore_neighbors(id, hops)   → graph traversal around an India entity
  india_graph_summary()               → domain breakdown of the India graph

━━━ LAYER 2: GLOBAL INTELLIGENCE GRAPH ━━━
Forces that move Indian markets from outside — geopolitics (sanctions, trade wars, conflicts),
climate (energy policy, carbon credits), technology (AI, semiconductors, supply chains),
and global corporate events (M&A, capacity expansions, regulatory shifts).

  global_search(query, limit)          → keyword search across all global entities
  global_semantic_search(query, limit) → embedding-based conceptual search
  global_explore_neighbors(id, hops)   → graph traversal around a global entity
  global_graph_summary()               → domain breakdown of the global graph

━━━ LAYER 3: LIVE MARKET DATA ━━━
Real-time TA signals, news sentiment, radar alerts, price history, portfolio.

  get_technical_signals(ticker)   → trend direction, momentum, support/resistance
  get_news_sentiment(ticker)      → sentiment score (-1 to +1) + headline summary
  get_radar_alerts(ticker)        → active opportunity radar alerts
  get_company_info(ticker)        → company metadata from the India market graph
  search_companies(query)         → find companies by name or ticker
  explore_connections(ticker)     → sector peers, executives, recent events
  get_insider_activity(ticker)    → bulk/block/insider trade data
  get_filings(ticker)             → quarterly results, BSE filing summaries
  get_portfolio()                 → user's watchlist and holdings
  get_macro_indicators()          → Nifty50, BankNifty, USD/INR, FII flows
  graph_summary()                 → overview of the India market graph

━━━ HOW TO ANALYSE — YOUR EDGE ━━━
Every answer must flow through three lenses before you draw a conclusion:

1. INDIA FUNDAMENTALS — What is the regulatory, macro, and sectoral backdrop?
   Pull from the India graph. Cite policy tailwinds or headwinds. Name competitors.

2. GLOBAL FORCES — What external risks or catalysts could flip the domestic story?
   Pull from the global graph. Be specific: "US Fed rate path", "China steel dumping",
   "OPEC+ cut", not generic "global uncertainty".

3. MARKET PULSE — What is the chart and the news saying right now?
   get_technical_signals() tells you trend and momentum.
   get_news_sentiment() tells you what the Street is reacting to today.
   Cross-check: does the chart confirm the fundamental story, or diverge?

4. VERDICT — Synthesise all three lenses into a direct recommendation:
   ▸ Situation in one sentence (what's happening and why it matters)
   ▸ Bull case (what would make this work)
   ▸ Bear case / key risks (what could go wrong)
   ▸ Your call — BUY / HOLD / AVOID — with a clear, plain-English rationale
   ▸ What to watch — one or two specific triggers the user should monitor

━━━ VOICE & STYLE ━━━
- Talk like a confident analyst at a morning call — crisp, direct, opinionated.
- Lead with the conclusion, not the preamble. Don't say "Let me analyse this for you."
- Use plain English. Never drop raw indicator names (ADX, MACD, StochRSI) — translate
  them: "momentum is building", "the stock is near a key floor", "sellers are in control".
- Be specific. "ICICI Bank's credit cost guidance of 1.2% is below the sector average" is
  better than "fundamentals look decent".
- Never invent facts. Only use what the tools return. Cite your source layer.
- For portfolio questions, start with get_portfolio().
- If data is missing or tools return nothing, say so plainly and work with what you have.
- You are talking to a retail investor — give them a verdict they can act on today.
"""


class VrishabRLM:
    def __init__(
        self,
        repo:        GraphRepository,
        ta:          TAEngine,
        bsnm:        BSNMEngine,
        radar:       OpportunityRadar,
        portfolio:   Optional[Dict]    = None,
        log_dir:     Optional[str]     = None,
        log_callback: Optional[Callable[[str], None]] = None,
        global_repo  = None,   # GlobalGraphRepository
        india_repo   = None,   # IndiaGraphRepository (GlobalGraphRepository instance)
    ):
        self.repo  = repo
        self.ta    = ta
        self.bsnm  = bsnm
        self.radar = radar
        self._log  = log_callback or (lambda msg: None)

        tools = build_tools(repo, ta, bsnm, radar, portfolio,
                            global_repo=global_repo, india_repo=india_repo)
        self._tools = tools  # kept for ask_quick()

        logger = RLMLogger(log_dir=log_dir) if log_dir else None

        self.rlm = RLM(
            backend       = "openai",
            backend_kwargs= {
                "model_name": LLM_MODEL_MAIN,
                "api_key":    OPENAI_API_KEY,
            },
            custom_tools        = tools,
            max_depth           = 2,
            max_iterations      = 8,
            verbose             = True,
            persistent          = False,
            compaction          = True,
            compaction_threshold_pct = 0.70,
            logger              = logger,
            on_iteration_start  = self._on_iter_start,
            on_iteration_complete = self._on_iter_complete,
            on_subcall_start    = self._on_subcall_start,
            on_subcall_complete = self._on_subcall_complete,
        )

        self._system = SYSTEM_PROMPT

    # ──────────────────────────────────────────
    # CALLBACKS (stream progress to frontend)
    # ──────────────────────────────────────────

    def _on_iter_start(self, depth: int, iteration: int):
        msg = f"[Vrishabh] Iteration {iteration} (depth={depth})\n"
        print(msg, end="", flush=True)
        self._log(msg)

    def _on_iter_complete(self, depth: int, iteration: int, duration: float):
        msg = f"[Vrishabh] Iteration {iteration} done ({duration:.1f}s)\n"
        print(msg, end="", flush=True)
        self._log(msg)

    def _on_subcall_start(self, depth: int, model: str, preview: str):
        msg = f"[Vrishabh] Sub-call depth={depth}: {preview[:80]}...\n"
        print(msg, end="", flush=True)
        self._log(msg)

    def _on_subcall_complete(self, depth: int, model: str, duration: float, error):
        if error:
            msg = f"[Vrishabh] Sub-call failed ({duration:.1f}s): {error}\n"
        else:
            msg = f"[Vrishabh] Sub-call done ({duration:.1f}s)\n"
        print(msg, end="", flush=True)
        self._log(msg)

    # ──────────────────────────────────────────
    # QUERY INTERFACE
    # ──────────────────────────────────────────

    def ask(self, question: str) -> str:
        prompt = f"{self._system}\n\nUser Question:\n{question}\n\nUse tools to explore and answer."

        try:
            result = self.rlm.completion(prompt)
        except Exception as e:
            best = getattr(e, "best_answer", None) or getattr(e, "response", None)
            if best:
                return str(best).strip()
            return f"Analysis incomplete: {e}"

        if result and result.response:
            return result.response.strip()

        if result and hasattr(result, "best_answer") and result.best_answer:
            return result.best_answer.strip()

        return "No answer generated — the RLM hit its iteration limit."

    # ──────────────────────────────────────────
    # QUICK MODE — 2-call LLM pipeline
    # ──────────────────────────────────────────

    def ask_quick(
        self,
        question: str,
        history:  Optional[list] = None,   # [{role: "user"|"assistant", content: "..."}]
    ) -> str:
        """
        2-call LLM pipeline (no RLM loop):
          Call 1 (Planner): decide which tools to call → JSON.
          Execute: run each tool call.
          Call 2 (Analyst): synthesise tool results → final answer.

        history: previous conversation turns (capped internally at 8 entries).
        """
        from openai import OpenAI
        from api.websearch import websearch as _websearch

        client  = OpenAI(api_key=OPENAI_API_KEY)
        history = list(history or [])[-8:]  # cap at 4 exchanges

        # ── Build tool catalogue for planner ──────────────
        tool_lines = [
            f"  {name}: {info['description']}"
            for name, info in self._tools.items()
        ]
        tool_lines.append(
            "  websearch(tags: list[str], prompt: str): "
            "Live web + news search for current market context."
        )
        tool_catalogue = "\n".join(tool_lines)

        planner_sys = (
            "You are Vrishabh's planning engine. "
            "Given a user question (and any prior conversation context), "
            "decide which tools to call to answer it well.\n\n"
            f"Available tools:\n{tool_catalogue}\n\n"
            "Rules:\n"
            "- For any ticker mentioned (including ones referenced in prior turns), "
            "always include get_technical_signals.\n"
            "- Always include a websearch for live market context.\n"
            "- Include india_search or india_semantic_search for India macro/policy context.\n"
            "- Max 7 tool calls total.\n"
            "- Return ONLY valid JSON, no other text:\n"
            '{"tool_calls": [{"tool": "tool_name", "args": {"arg1": "val1"}}, ...]}'
        )

        # Planner sees full conversation history for follow-up context
        planner_messages: list = [{"role": "system", "content": planner_sys}]
        planner_messages.extend(history)
        planner_messages.append({"role": "user", "content": question})

        self._log("[Quick] Planner: deciding tool calls…\n")
        try:
            plan_resp = client.chat.completions.create(
                model          = LLM_MODEL_MAIN,
                messages       = planner_messages,
                response_format = {"type": "json_object"},
                temperature    = 0,
            )
            plan       = json.loads(plan_resp.choices[0].message.content)
            tool_calls = plan.get("tool_calls", [])
        except Exception as e:
            self._log(f"[Quick] Planner failed: {e}\n")
            return f"Planner error: {e}"

        # ── Execute tool calls ─────────────────────────────
        tool_results = []
        for call in tool_calls[:7]:
            name = call.get("tool", "")
            args = call.get("args", {}) or {}
            self._log(f"[Quick] Calling {name}({list(args.keys())})\n")
            try:
                if name == "websearch":
                    result = _websearch(
                        args.get("tags", []),
                        args.get("prompt", question),
                    )
                elif name in self._tools:
                    result = self._tools[name]["tool"](**args)
                else:
                    result = {"error": f"Unknown tool: {name}"}
            except Exception as e:
                result = {"error": str(e)}
            tool_results.append({"tool": name, "args": args, "result": result})

        # ── Call 2: Analyst ───────────────────────────────
        self._log("[Quick] Analyst: synthesising results…\n")
        results_text = json.dumps(tool_results, ensure_ascii=False, indent=2, default=str)

        analyst_user_msg = (
            f"You are Vrishabh — an AI financial analyst for the Indian retail investor.\n\n"
            f"User question: {question}\n\n"
            f"Live tool results:\n{results_text}\n\n"
            "Answer the question clearly and specifically based only on the data above. "
            "Use plain English — no raw indicator names (ADX, StochRSI etc.). "
            "Format in markdown with clear sections. Be specific and actionable for a retail investor. "
            "Where relevant, refer back to the conversation history to provide continuity."
        )

        # Analyst sees full conversation history for continuity
        analyst_messages: list = []
        analyst_messages.extend(history)
        analyst_messages.append({"role": "user", "content": analyst_user_msg})

        try:
            ans_resp = client.chat.completions.create(
                model       = LLM_MODEL_MAIN,
                messages    = analyst_messages,
                temperature = 0.3,
            )
            return ans_resp.choices[0].message.content.strip()
        except Exception as e:
            return f"Analyst error: {e}"
