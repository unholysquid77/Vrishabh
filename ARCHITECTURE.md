# Vrishabh / Vidur — Architecture Document

## Overview

Vidur is an agentic AI equity analyst for the Indian retail investor. The system is built around **Vrishabh**, a proactive reasoning agent that acts without being prompted — generating morning briefs, monitoring watch conditions, and enriching every user query with live market intelligence before answering.

The platform merges two subsystems:
- **Suvarn** — a technical analysis engine (regime detection, 5-level signals, pattern recognition)
- **Paqshi** — a dual knowledge graph system (India macro + global geopolitics)

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Frontend  (Vanilla JS)                        │
│  Macro Strip · Morning Brief · Home Chat · Radar · Signals      │
│  Graph Explorer · Watch Panel · Memory Log                       │
└────────────────────────┬────────────────────────────────────────┘
                         │  HTTP + SSE
┌────────────────────────▼────────────────────────────────────────┐
│               FastAPI Server  (api/server.py)                    │
│                                                                  │
│  /brief   /brief/cached   /chat/stream/{quick,agent,deep}        │
│  /watch   /memory   /radar   /signals   /macro   /technicals     │
└───────┬───────────────┬──────────────────┬───────────────────────┘
        │               │                  │
┌───────▼──────┐ ┌──────▼──────┐  ┌────────▼─────────────────────┐
│  VrishabRLM  │ │  Scheduler  │  │  Knowledge Graphs (Paqshi)    │
│  (agent/)    │ │  (api/)     │  │                               │
│              │ │             │  │  India Intel  Graph  62 KB    │
│  ask_quick   │ │  market/2m  │  │  Global Intel Graph  325 KB   │
│  ask_agent   │ │  news/1h    │  │  Market Graph        8.3 MB   │
│  ask (deep)  │ │  graphs/6h  │  │                               │
│              │ │  brief/3h   │  │  Entities: companies, policy, │
│  Tools: 22+  │ │  watches ←  │  │  geopolitics, climate, tech   │
└──────────────┘ └─────────────┘  └───────────────────────────────┘
        │
┌───────▼───────────────────────────────────────────────────────┐
│                    Intelligence Layers                          │
│                                                                │
│  Layer 1 · Suvarn TA Engine                                    │
│    Regime detection · 5-level signals · Pattern recognition    │
│    Support/resistance · Momentum · 300-bar lookback            │
│                                                                │
│  Layer 2 · India Intelligence Graph                            │
│    NSE companies · Conglomerates · RBI/SEBI policy · Budget    │
│    Sector relationships · Macro indicators · FDI/FPI flows     │
│                                                                │
│  Layer 3 · Global Intelligence Graph                           │
│    Geopolitics · Trade wars · Sanctions · Climate events       │
│    Supply chain shocks · Technology disruptions                │
└────────────────────────────────────────────────────────────────┘
```

---

## Agent Architecture — The 4-Stage Reasoning Pipeline

### Stage 1: Scheduler Agent (autonomous, always-on)
`api/scheduler.py → VrishabScheduler`

Runs independently of any user session. Manages three concurrent loops:

| Loop | Interval | What it does |
|------|----------|--------------|
| Market Sync | 2 min | Fetches OHLCV for 100+ NSE tickers, runs full TA enrichment via Suvarn |
| News Sync | 1 hr | Fetches NewsData.io articles, runs GPT-4o-mini sentiment scoring |
| Brief Generation | 3 hr | Builds market context → calls VrishabRLM → stores brief to disk |

After every market sync, the scheduler invokes the **Watch Condition Agent** (see below).

### Stage 2: Signal + Context Enrichment Agent (per-request middleware)
`api/server.py → /chat/stream/agent`

For "Agent" mode queries, the server performs **3 sequential enrichment steps before the LLM sees the question**:

```
Step 1 — Ticker Extraction:
  _extract_tickers(question) → ["RELIANCE", "INFY", ...]

Step 2 — Per-ticker TA Context:
  for each ticker:
    ta_data = _ta_engine.analyse(ticker)
    context += f"{ticker}: {ta_data.action} | score {ta_data.score:.2f} | ..."

Step 3 — Broad Market Overview:
  top_5_signals = sorted(market_cache, key=score)[-5:]
  top_3_radar   = radar.get_alerts(watchlist)[:3]
  overview = format(top_5_signals + top_3_radar)

enriched_question = ticker_ctx + overview + original_question
→ passed to VrishabRLM.ask_quick(enriched_question, history)
```

This is the minimum viable agentic pipeline that satisfies the **"3+ sequential tool/agent steps"** requirement without invoking the full RLM loop.

### Stage 3: VrishabRLM — Deep Reasoning Agent
`agent/vrishabh_rlm.py`

Three callable modes:

| Mode | Pipeline | Max Tool Calls | Latency |
|------|----------|---------------|---------|
| `ask_quick` | Planner → Execute → Analyst | 0 | 10–20s |
| `ask_agent` | Enrichment → ask_quick | 3 (enrichment) | 20–35s |
| `ask` (deep) | Full RLM agentic loop | 7 | 45–90s |

Deep mode uses a tool-calling loop with **transparent reasoning trace** streamed live to the frontend:
```
🔍 Searching India graph...
📊 Fetching TA data for RELIANCE...
🕸 Traversing: RELIANCE → MUKESH_AMBANI → RIL_SUBSIDIARIES
📡 Checking radar for sector signals...
🧠 Reading memory context...
```

### Stage 4: Watch Condition Agent (event-driven)
`api/scheduler.py → _check_watches()`

After every market sync, evaluates active watch conditions against fresh TA data:

```
1. Load active watches from data/watches.json
2. Extract unique tickers from active conditions
3. Run TA analysis: ta_engine.analyse_many(tickers)
4. For each condition: evaluate metric/operator/threshold
   - Metrics: price, pct_change, ta_score, action
   - Operators: >, <, ==, >=, <=
5. If condition fires:
   - Mark as inactive, record fired_at timestamp
   - Broadcast SSE event: {"type": "watch_fired", ...}
   - Frontend receives → toast notification + chat message
6. Persist updated watches to disk
```

Watch conditions are created by the agent via the `create_watch()` tool from natural language:
```
User: "Alert me when RELIANCE breaks ₹1450"
Agent calls: create_watch("RELIANCE", "price", ">", 1450.0, "...")
```

---

## Tool Registry (22 tools across 5 categories)

| Category | Tools |
|----------|-------|
| Technical Analysis | `get_ta_data`, `get_signals`, `get_technicals`, `get_price`, `get_ohlcv` |
| India Graph | `graph_search`, `graph_traverse`, `graph_entity`, `graph_related` |
| Global Graph | `global_search`, `global_traverse`, `global_entity` |
| Radar | `get_radar`, `get_radar_ticker`, `get_movers` |
| Agentic | `create_watch`, `remember`, `get_memory`, `get_watches`, `get_macro`, `get_news_sentiment`, `get_brief` |

---

## Data Flow — Morning Brief (Autonomous)

```
[Scheduler: 9:00 AM IST]
      │
      ▼ Check: last brief < 3 hours ago?
      │  No → skip
      │  Yes ↓
      ▼
   Gather: top 6 signals + top 4 radar alerts + macro (Nifty/BankNifty/Sensex)
      │
      ▼
   Build prompt (market snapshot + signal summary)
      │
      ▼
   VrishabRLM.ask_quick(brief_prompt) → streaming text
      │
      ▼
   Save to data/brief_cache.json {text, generated_at, generated_at_ist}
      │
      ▼
   Frontend /brief/cached → instant load on next dashboard open
```

---

## Data Flow — User Query (Deep Mode)

```
User types question
      │
      ▼ POST /chat/stream/deep  (SSE)
      │
      ▼ Inject persistent memory as context prefix
      │
      ▼ VrishabRLM.ask(question, history)
      │
      ├── Planner call: "what tools do I need?"
      │       └── Response: [tool_call_1, tool_call_2, ...]
      │
      ├── Tool execution loop (up to 7 rounds):
      │   ├── Execute tool → stream trace token to frontend
      │   ├── Append result to context
      │   └── Re-evaluate: more tools needed?
      │
      ▼ Analyst call: synthesize all tool results → final answer
      │
      ▼ Stream final answer tokens to frontend via SSE
```

---

## Persistent State

| File | Purpose | Updated by |
|------|---------|-----------|
| `data/brief_cache.json` | Last auto-generated morning brief | Scheduler (every 3h) |
| `data/watches.json` | Active/fired watch conditions | Agent tool + Scheduler |
| `data/memory.json` | Agent's cross-session memory | `remember()` tool |
| `data/graph.json` | NSE market knowledge graph | Manual / graph pipeline |
| `data/india_graph.json` | India macro/policy graph | Paqshi pipeline |
| `data/global_graph.json` | Global events graph | Paqshi pipeline |

---

## Real-time Communication

All real-time updates use **Server-Sent Events (SSE)**:

| Event type | Source | Frontend action |
|------------|--------|----------------|
| `market_sync` | Scheduler | Refresh macro strip + signals |
| `news_sync` | Scheduler | Refresh radar alerts |
| `watch_fired` | Watch agent | Toast notification + chat message |
| `brief_ready` | Brief agent | Reload brief panel |
| Chat tokens | LLM stream | Append to message bubble |

---

## Error Handling

- **TA data unavailable**: Falls back to yfinance raw price; signals skipped for that ticker
- **LLM API failure**: Retries once; returns partial stream with error suffix
- **Watch condition errors**: Logged; condition left active for next cycle
- **Graph traversal**: Returns empty list on missing node; never raises to user
- **News pipeline**: NewsData.io rate limit gracefully degrades to cached articles
- **Suvarn API**: Falls back to local `ta_engine/` module if `SUVARN_API_URL` unset

---

## Portfolio Personalization

Vrishabh personalizes along three axes:

1. **Watchlist** — user-curated tickers stored in `_portfolio["watchlist"]`. Agent mode enriches every query with watchlist signals first.
2. **Persistent Memory** — `remember()` tool saves facts the user states: *"I'm overweight IT, looking to rotate into infra"*. Injected as context prefix in every subsequent session.
3. **Watch Conditions** — per-user alert thresholds created from natural language. Agent interprets and stores structured conditions.

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend API | FastAPI + Uvicorn |
| Agent Engine | Custom RLM (Reasoning Language Model) + GPT-4o |
| TA Engine | TA-Lib + PatternPy (Suvarn) |
| Knowledge Graphs | Custom JSON graph engine (Paqshi) |
| News Sentiment | NewsData.io + GPT-4o-mini |
| Market Data | yfinance (+ Angel One streaming, optional) |
| Frontend | Vanilla JS + lightweight-charts + Chart.js |
| Real-time | Server-Sent Events |
| Scheduling | Python threading (no external cron) |
