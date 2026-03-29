# Vidur — AI for the Indian Investor

> **Vrishabh** is an agentic AI equity analyst built for the Indian retail investor. It synthesises live market data, technical signals, news sentiment, and two intelligence knowledge graphs to give actionable, context-aware analysis — automatically, and without being asked.

Built for the ET Hackathon · Merges [Paqshi](https://github.com/) (intelligence graphs) + [Suvarn](https://github.com/) (TA engine)

---

## The Problem

Indian retail investors are drowning in noise. Terminals cost ₹20,000/month. Financial advisors are expensive and conflicted. Free tools give raw data with no synthesis. The retail investor — who drives 45% of NSE daily volume — has no intelligent co-pilot.

## The Solution

Vrishabh is a personal AI analyst that:
- Wakes up before you do and generates a morning brief
- Watches your conditions 24/7 and alerts you the moment they're met
- Remembers what you discussed last week and builds on it
- Answers questions across three intelligence layers: live TA, India macro graph, and global events graph

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (Vanilla JS)                 │
│  Dashboard · Radar · Chart Intelligence · Signals · Graph   │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP + SSE
┌──────────────────────────▼──────────────────────────────────┐
│                    FastAPI Server (api/server.py)            │
│                                                              │
│  /brief  /chat/stream/{quick,agent,deep}  /watch  /memory   │
│  /radar  /signals  /macro  /movers  /technicals             │
└──────┬────────────────┬──────────────────┬──────────────────┘
       │                │                  │
┌──────▼──────┐  ┌──────▼──────┐  ┌───────▼──────────────────┐
│  VrishabRLM │  │  Scheduler  │  │   Knowledge Graphs        │
│             │  │             │  │                            │
│  ask_quick  │  │  market/2m  │  │  Market Graph  (8.3 MB)   │
│  ask_agent  │  │  news/1h    │  │  India Intel   (62 KB)    │
│  ask (deep) │  │  graphs/6h  │  │  Global Intel  (325 KB)   │
│             │  │  brief/3h ← │  │                            │
│  Tools: 20+ │  │  watches ←  │  │  Entities: companies,     │
│  graph tools│  │             │  │  policy, geopolitics,      │
│  TA tools   │  │  SSE bus →  │  │  climate, technology       │
│  radar tools│  │  frontend   │  │                            │
└─────────────┘  └─────────────┘  └────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────┐
│              Intelligence Layers                             │
│                                                              │
│  Layer 1 · Suvarn TA Engine                                  │
│    Regime detection, 5-level signals, pattern recognition    │
│    Support/resistance, momentum, 300-bar lookback            │
│                                                              │
│  Layer 2 · India Intelligence Graph (Paqshi)                 │
│    NSE companies, conglomerates, RBI/SEBI policy, budget     │
│    Sector relationships, macro indicators, FDI/FPI flows     │
│                                                              │
│  Layer 3 · Global Intelligence Graph (Paqshi)                │
│    Geopolitics, trade wars, sanctions, climate events        │
│    Supply chain shocks, technology disruptions               │
└─────────────────────────────────────────────────────────────┘
```

### Agent Modes

| Mode | Pipeline | Latency | When to use |
|------|----------|---------|-------------|
| **Quick** | Ticker context → `ask_quick` | ~10–20s | Fast checks, price levels, watchlist |
| **Agent** | Market overview + signals + radar → `ask_quick` | ~20–35s | Well-informed, dynamic questions |
| **Deep** | Full RLM agentic loop (up to 7 tool calls) | ~45–90s | Research, thesis building, sector analysis |

### Agentic Features

- **Scheduled Briefs** — Scheduler generates a morning brief every ~3 hours during IST market hours (9am–5pm), stored in `data/brief_cache.json`. Dashboard loads instantly from cache.
- **Watch Conditions** — Tell Vrishabh *"alert me when RELIANCE breaks ₹1450"*. Agent creates a structured condition via `create_watch()` tool. Scheduler checks after every market sync. Fires as SSE → toast + chat notification.
- **Persistent Memory** — Agent uses `remember()` tool to save key facts across sessions. Injected as context prefix in every subsequent chat.
- **Transparent Reasoning** — Deep mode shows live tool-call trace with icons: 🔍 search, 📊 TA data, 🕸 graph traversal, 📡 radar, 🧠 memory.

---

## Setup

### Prerequisites

- Python 3.11+
- TA-Lib C library (see below)
- OpenAI API key (GPT-4o)
- NewsData.io API key (free tier works)

### 1. Clone

```bash
git clone https://github.com/YOUR_USERNAME/vidur.git
cd vidur
```

### 2. Install TA-Lib

TA-Lib requires the C library to be installed first.

**Windows:**
```bash
# Download the wheel from https://github.com/cgohlke/talib-build/releases
pip install TA_Lib-0.4.28-cp311-cp311-win_amd64.whl
```

**Linux/macOS:**
```bash
# Ubuntu/Debian
sudo apt-get install libta-lib0-dev
# macOS
brew install ta-lib

pip install TA-Lib
```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt

# PatternPy (chart pattern detection)
pip install git+https://github.com/keithorange/PatternPy.git
```

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your API keys
```

Required keys:
- `OPENAI_API_KEY` — GPT-4o for agent reasoning and brief generation
- `NEWSDATA_API_KEY` — News sentiment pipeline

Optional:
- `INDIANAPI_KEY` — Richer Indian market data (insider trades, filings)
- `ACLED_EMAIL` / `ACLED_PASSWORD` — Geopolitical conflict data for the global graph

### 5. Run

```bash
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000` in your browser.

> **First run:** The market data pipeline and news pipeline will kick off automatically. Graph data is pre-seeded. Allow ~2 minutes for initial sync before the brief and signals populate.

---

## Project Structure

```
vidur/
├── main.py                  # Entry point
├── config.py                # API keys, ticker list, model config
├── requirements.txt
│
├── api/
│   ├── server.py            # FastAPI app — all HTTP endpoints
│   ├── scheduler.py         # Background pipelines + SSE bus
│   └── ...
│
├── agent/
│   ├── vrishabh_rlm.py      # VrishabRLM — agentic reasoning engine
│   └── tools.py             # 22 tools: TA, graphs, radar, memory, watches
│
├── pipelines/
│   ├── market_data.py       # yfinance OHLCV + TA enrichment
│   └── news.py              # NewsData.io sentiment pipeline
│
├── graph/                   # India market knowledge graph
├── india_graph/             # India intelligence graph (Paqshi)
├── global_graph/            # Global intelligence graph (Paqshi)
├── radar/                   # Opportunity radar (TA + news signals)
├── suvarn_client/           # TA engine client (Suvarn)
├── ta_engine/               # Regime detection, pattern recognition
│
├── data/
│   ├── graph.json           # India market graph (~8.3 MB)
│   ├── india_graph.json     # India intel graph (~62 KB)
│   ├── global_graph.json    # Global intel graph (~325 KB)
│   ├── brief_cache.json     # Auto-generated morning brief
│   ├── watches.json         # Active watch conditions
│   └── memory.json          # Persistent agent memory
│
└── frontend/
    └── index.html           # Single-page app (vanilla JS, no build step)
```

---

## Key Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /brief` | Stream live morning brief (SSE) |
| `GET /brief/cached` | Return scheduler-generated brief |
| `POST /chat/stream/quick` | Quick chat with history (SSE) |
| `POST /chat/stream/agent` | Agent chat with market overview injected (SSE) |
| `GET /chat/stream?q=...` | Deep RLM chat — full tool loop (SSE) |
| `GET /macro` | Nifty50, BankNifty, Sensex, USD/INR |
| `GET /radar/compressed` | Opportunity radar alerts |
| `GET /signals` | Top TA signals by conviction |
| `GET /watch` | List watch conditions |
| `POST /watch` | Create watch condition |
| `GET /memory` | List persistent memory entries |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + Uvicorn |
| Agent | RLM (Reasoning Language Model framework) + GPT-4o |
| TA Engine | TA-Lib + PatternPy (Suvarn) |
| Knowledge Graphs | Custom JSON graph engine (Paqshi) |
| News Sentiment | NewsData.io + GPT-4o-mini |
| Market Data | yfinance |
| Frontend | Vanilla JS + lightweight-charts + Chart.js |
| Real-time | Server-Sent Events (SSE) |

---

## Environment Variables

See `.env.example` for the full list. Minimum required to run:

```
OPENAI_API_KEY=sk-...
NEWSDATA_API_KEY=pub_...
```

---

## License

MIT
