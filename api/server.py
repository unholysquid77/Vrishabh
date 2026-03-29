"""
Vrishabh FastAPI Server
"""

import asyncio
import datetime
import io
import json
import os
import sys
import threading
import uuid
from typing import Any, Dict, List, Optional

# Ensure stdout/stderr use UTF-8 on Windows (avoids charmap encode errors from
# LLM responses containing Unicode like ₹, →, ▸ etc.)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import (
    OPENAI_API_KEY, NIFTY_500_TICKERS, GRAPH_FILE,
    NEWSDATA_API_KEY, GLOBAL_GRAPH_FILE, INDIA_GRAPH_FILE,
    ACLED_EMAIL, ACLED_PASSWORD, INDIANAPI_KEY,
)
from graph import FinanceGraph, GraphRepository
from pipelines import MarketDataPipeline, NewsPipeline
from suvarn_client import SuvarnTAClient as TAEngine, SuvarnBSNMClient as BSNMEngine
from radar import OpportunityRadar
from agent import VrishabRLM
from api.indian_api import IndianAPIClient
from api.radar_compress import compress_alerts
from global_graph.orchestrator import GlobalGraphOrchestrator
from india_graph.orchestrator import IndiaGraphOrchestrator
from api.scheduler import (
    VrishabScheduler,
    _load_brief_cache, _save_brief_cache,
    _load_watches, _save_watches,
    _load_memory, _save_memory,
)


# ──────────────────────────────────────────────
# APP INIT
# ──────────────────────────────────────────────

app = FastAPI(title="Vrishabh", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static frontend
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ──────────────────────────────────────────────
# SHARED STATE
# ──────────────────────────────────────────────

_graph      = FinanceGraph()
_repo       = GraphRepository(_graph, GRAPH_FILE, openai_key=OPENAI_API_KEY)
_market     = MarketDataPipeline(_repo)
_news       = NewsPipeline(_repo)
_ta         = TAEngine()
_bsnm       = BSNMEngine(openai_key=OPENAI_API_KEY)
_radar      = OpportunityRadar(_repo, _ta, _bsnm)

# Portfolio (in-memory for now; could be persisted)
_portfolio  = {"watchlist": list(NIFTY_500_TICKERS[:20]), "holdings": {}}

_rlm_log_buffer: List[str] = []
_rlm_log_lock   = threading.Lock()

def _rlm_log_cb(msg: str):
    with _rlm_log_lock:
        _rlm_log_buffer.append(msg)

# Global intelligence graph
_global_orch = GlobalGraphOrchestrator(
    openai_key     = OPENAI_API_KEY,
    newsdata_key   = NEWSDATA_API_KEY,
    graph_file     = GLOBAL_GRAPH_FILE,
    log_callback   = _rlm_log_cb,
    acled_email    = ACLED_EMAIL,
    acled_password = ACLED_PASSWORD,
)

# India intelligence graph
_india_orch = IndiaGraphOrchestrator(
    openai_key   = OPENAI_API_KEY,
    newsdata_key = NEWSDATA_API_KEY,
    graph_file   = INDIA_GRAPH_FILE,
    log_callback = _rlm_log_cb,
)

_indian_api = IndianAPIClient(api_key=INDIANAPI_KEY)

_vrishabh_rlm = VrishabRLM(
    repo        = _repo,
    ta          = _ta,
    bsnm        = _bsnm,
    radar       = _radar,
    portfolio   = _portfolio,
    global_repo = _global_orch.repo,
    india_repo  = _india_orch.repo,
    log_dir     = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "rlm_logs"),
    log_callback = _rlm_log_cb,
)

# ──────────────────────────────────────────────
# SCHEDULER
# ──────────────────────────────────────────────

_scheduler = VrishabScheduler(
    market      = _market,
    news        = _news,
    india_orch  = _india_orch,
    global_orch = _global_orch,
    portfolio   = _portfolio,
    ta          = _ta,
    bsnm        = _bsnm,
    radar       = _radar,
    rlm         = _vrishabh_rlm,
    insights_topk = 3,
)


# ──────────────────────────────────────────────
# STARTUP
# ──────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    """Load persisted graphs, then hand off to the background scheduler."""
    _repo.load()
    print(f"[Vrishabh] Market graph loaded: {_repo.summary()}")
    _india_orch.load()
    print(f"[Vrishabh] India intelligence graph loaded: {_india_orch.summary()}")
    _global_orch.load()
    print(f"[Vrishabh] Global intelligence graph loaded: {_global_orch.summary()}")
    # Give the scheduler a reference to the running event loop (for SSE push)
    _scheduler.set_loop(asyncio.get_event_loop())
    _scheduler.start()
    print("[Vrishabh] Scheduler running — market every 2 min, news/insights every 1 hr, graphs every 6 hr")


# ──────────────────────────────────────────────
# HEALTH / SCHEDULER STATUS / SSE
# ──────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "graph": _repo.summary(), "scheduler": _scheduler.get_status()}


@app.get("/scheduler/status")
def scheduler_status():
    """Return per-pipeline sync state (last run, elapsed, errors)."""
    return _scheduler.get_status()


@app.post("/scheduler/trigger/{pipeline}")
def scheduler_trigger(pipeline: str):
    """
    Manually trigger a specific pipeline immediately.
    pipeline: market | news | india | global | graphs | insights
    """
    valid = {"market", "news", "india", "global", "graphs", "insights"}
    if pipeline not in valid:
        raise HTTPException(400, f"Unknown pipeline '{pipeline}'. Valid: {sorted(valid)}")
    _scheduler.run_now(pipeline)
    return {"status": "triggered", "pipeline": pipeline}


@app.get("/stream")
async def sse_stream():
    """
    Server-Sent Events stream — pushes scheduler status + market data updates
    to all connected browser clients in real-time.

    The frontend connects once with EventSource('/stream') and receives:
      {type: 'heartbeat',    ts, status}          — every 30s
      {type: 'sync_start',   pipeline, ts}
      {type: 'sync_done',    pipeline, elapsed, ts, data?}
      {type: 'sync_error',   pipeline, error, ts}
      {type: 'market_data',  data, ts}            — after every market sync
    """
    q = _scheduler.bus.subscribe()

    # Send an immediate status snapshot so the client doesn't wait 30s
    import json as _json
    hello = "data: " + _json.dumps({
        "type": "hello",
        "ts":   __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "status": _scheduler.get_status(),
    }, default=str) + "\n\n"

    async def generator():
        yield hello
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=45)
                    yield payload
                except asyncio.TimeoutError:
                    # Yield a keep-alive comment so the connection doesn't drop
                    yield ": keepalive\n\n"
        finally:
            _scheduler.bus.unsubscribe(q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# Backwards-compat shim for old /sync/now calls from any existing clients
@app.post("/sync/now")
def sync_now():
    _scheduler.run_now("market")
    _scheduler.run_now("news")
    return {"status": "triggered"}


# ──────────────────────────────────────────────
# MACRO / INDEX DATA
# ──────────────────────────────────────────────

_INDICES = {
    "nifty50":   ("^NSEI",    "Nifty 50",   "^NSEI"),
    "banknifty": ("^NSEBANK", "Bank Nifty", "^NSEBANK"),
    "sensex":    ("^BSESN",   "Sensex",     "^BSESN"),
    "usdinr":    ("USDINR=X", "USD/INR",    None),   # no chart for forex
}

@app.get("/macro")
def get_macro():
    import yfinance as yf
    import pandas as pd
    result = {}
    for key, (yf_ticker, label, chart_ticker) in _INDICES.items():
        try:
            df = yf.download(yf_ticker, period="5d", progress=False, auto_adjust=True)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.rename(columns={c: c.lower() for c in df.columns})
            if df.empty or len(df) < 2:
                result[key] = {"label": label, "price": None, "pct_change": None, "chart_ticker": chart_ticker}
                continue
            last = float(df["close"].iloc[-1])
            prev = float(df["close"].iloc[-2])
            pct  = round((last - prev) / prev * 100, 2)
            result[key] = {"label": label, "price": round(last, 2), "pct_change": pct, "chart_ticker": chart_ticker}
        except Exception as e:
            result[key] = {"label": label, "price": None, "pct_change": None, "chart_ticker": chart_ticker}
    return result


# ──────────────────────────────────────────────
# MARKET MOVERS
# ──────────────────────────────────────────────

@app.get("/movers")
def get_movers(topk: int = Query(3, le=10)):
    tickers = _portfolio["watchlist"][:40]
    sigs = _ta.analyse_many(tickers)
    enriched = [s.to_dict() for s in sigs.values() if s.pct_change is not None]
    enriched.sort(key=lambda x: x.get("pct_change") or 0, reverse=True)

    # Supplement with IndianAPI live movers if available and TA data is thin
    ia_movers = _indian_api.get_movers(topk=topk) if _indian_api.available else {}
    return {
        "gainers":    enriched[:topk],
        "losers":     list(reversed(enriched[-topk:])) if len(enriched) >= topk else list(reversed(enriched)),
        "ia_gainers": ia_movers.get("gainers", []),  # live from IndianAPI (may be empty)
        "ia_losers":  ia_movers.get("losers",  []),
    }


# ──────────────────────────────────────────────
# TRADING INSIGHTS (RLM-powered)
# ──────────────────────────────────────────────

def _pick_top_tickers(topk: int):
    """Return (gainers, losers, all_tickers, sig_map) from the watchlist."""
    import re as _re, json as _json
    tickers  = _portfolio["watchlist"][:40]
    sigs     = _ta.analyse_many(tickers)
    enriched = sorted(
        [s for s in sigs.values() if s.pct_change is not None],
        key=lambda s: s.pct_change or 0, reverse=True,
    )
    gainers     = [s.ticker for s in enriched[:topk]]
    losers      = [s.ticker for s in enriched[-topk:]]
    # Deduplicate while preserving order (a ticker could appear in both lists)
    seen: set   = set()
    all_tickers = []
    for t in gainers + losers:
        if t not in seen:
            seen.add(t)
            all_tickers.append(t)
    sig_map = {s.ticker: s.to_dict() for s in sigs.values()}
    return gainers, losers, all_tickers, sig_map


def _dedup_insights(insights: list, sig_map: dict) -> list:
    """Ensure exactly one insight per ticker, enrich with TA numbers."""
    seen: set = set()
    deduped   = []
    for ins in insights:
        t = (ins.get("ticker") or "").upper()
        if not t or t in seen:
            continue
        seen.add(t)
        sd = sig_map.get(t, {})
        ins.setdefault("pct_change", sd.get("pct_change"))
        ins.setdefault("last_close", sd.get("last_close"))
        ins.setdefault("score",      sd.get("score"))
        ins.setdefault("action",     sd.get("suggested_action", "HOLD"))
        deduped.append(ins)
    return deduped


@app.post("/insights")
def generate_insights(topk: int = Query(5, le=10)):
    """
    Deep insights via VrishabRLM — uses India/Global knowledge graphs + all tools.
    Returns one card per ticker (deduped).
    """
    import re as _re, json as _json

    gainers, losers, all_tickers, sig_map = _pick_top_tickers(topk)

    prompt = (
        f"You are generating trading insights for an Indian retail investor.\n"
        f"Analyse these stocks: {', '.join(all_tickers)}\n"
        f"Top gainers today: {', '.join(gainers)}\n"
        f"Top losers today:  {', '.join(losers)}\n\n"
        f"For EACH stock use ALL available tools "
        f"(india_search, global_search, get_technical_signals, get_news_sentiment, get_radar_alerts).\n"
        f"Then return ONLY a JSON object — no text before or after:\n\n"
        f'{{"insights": [{{'
        f'"ticker":"TICKER","action":"BUY|SELL|HOLD",'
        f'"summary":"...","india_context":"...","global_context":"...",'
        f'"market_signals":"...","key_risks":"...","suggestion":"..."'
        f'}}]}}\n\n'
        f"Produce EXACTLY ONE entry per ticker ({len(all_tickers)} total). Return ONLY the JSON."
    )

    try:
        raw = _vrishabh_rlm.ask(prompt)
    except Exception as e:
        raise HTTPException(500, f"RLM error: {e}")

    raw_clean = _re.sub(r'```(?:json)?\s*', '', raw).strip()
    m         = _re.search(r'\{[\s\S]*?"insights"[\s\S]*\}', raw_clean)
    if not m:
        raise HTTPException(500, f"RLM returned no JSON with 'insights'. Raw: {raw[:400]}")
    candidate = m.group(0)[: m.group(0).rfind("}") + 1]
    try:
        parsed = _json.loads(candidate)
    except Exception:
        try:
            parsed = _json.loads(_re.sub(r'[\x00-\x1f\x7f]', '', candidate))
        except Exception as e2:
            raise HTTPException(500, f"JSON parse error: {e2}. Raw: {raw[:400]}")

    parsed["insights"] = _dedup_insights(parsed.get("insights", []), sig_map)
    return parsed


@app.post("/insights/quick")
def generate_insights_quick(topk: int = Query(5, le=10)):
    """
    Quick insights via 2-call LLM pipeline (no RLM loop).
    Call 1: planner emits all required data-fetch calls as JSON.
    Execute: runs tool calls (including live websearch).
    Call 2: analyst synthesises all gathered data into insight cards.
    """
    from api.llm_insights import run_llm_insights  # type: ignore

    gainers, losers, all_tickers, sig_map = _pick_top_tickers(topk)

    try:
        result = run_llm_insights(
            tickers=all_tickers,
            ta=_ta,
            bsnm=_bsnm,
            radar=_radar,
            sig_map=sig_map,
        )
    except Exception as e:
        raise HTTPException(500, f"LLM insights error: {e}")

    # Tag each insight with gainer/loser role for the frontend
    gainer_set = set(gainers)
    loser_set  = set(losers)
    for ins in result.get("insights", []):
        t = ins.get("ticker", "")
        ins["role"] = "gainer" if t in gainer_set else "loser" if t in loser_set else "neutral"

    return result


# ──────────────────────────────────────────────
# FRONTEND
# ──────────────────────────────────────────────

@app.get("/")
def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


# ──────────────────────────────────────────────
# GRAPH ENDPOINTS
# ──────────────────────────────────────────────

@app.get("/graph/data")
def graph_data():
    """Full graph for vis.js visualization."""
    return _repo.full_graph_data()


@app.get("/graph/company/{ticker}")
def company_graph(ticker: str):
    """Subgraph centered on a company (2-hop)."""
    return _repo.get_company_graph(ticker.upper())


@app.get("/graph/summary")
def graph_summary():
    return _repo.summary()


# ──────────────────────────────────────────────
# COMPANY / ENTITY ENDPOINTS
# ──────────────────────────────────────────────

@app.get("/companies/search")
def search_companies(q: str = Query(..., min_length=1)):
    from graph.entities import EntityType
    results = _repo.search_partial(q, limit=15)
    return [
        {
            "id":     n.id,
            "ticker": n.ticker,
            "name":   n.canonical_name,
            "type":   n.ontology_type,
            "sector": n.attributes.get("sector"),
        }
        for n in results
    ]


@app.get("/companies/{ticker}")
def get_company(ticker: str):
    node = _graph.get_company_node(ticker.upper())
    if not node:
        raise HTTPException(404, f"{ticker} not found in graph.")
    return _repo._serialize_entity(node)


# ──────────────────────────────────────────────
# TECHNICAL ANALYSIS
# ──────────────────────────────────────────────

@app.get("/technicals/bulk")
def bulk_technicals(tickers: str = Query(..., description="Comma-separated tickers")):
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    signals     = _ta.analyse_many(ticker_list)
    return {t: s.to_dict() for t, s in signals.items()}


@app.get("/technicals/{ticker}")
def get_technicals(ticker: str):
    sig = _ta.analyse(ticker.upper())
    if not sig:
        raise HTTPException(404, f"Insufficient data for {ticker}.")
    return sig.to_dict()


@app.get("/backtest/{ticker}")
def run_backtest(ticker: str):
    """
    Backtest the simple MACD+Supertrend+ADX+BB strategy on ~3 years of OHLCV.
    Returns equity curve (vs buy-and-hold) + performance metrics.
    """
    from ta_engine.backtest import run as _backtest
    from pipelines.market_data import fetch_ohlcv
    df = fetch_ohlcv(ticker.upper(), bars=750)   # ~3 years of trading days
    if df is None or len(df) < 80:
        raise HTTPException(404, f"Insufficient data for {ticker}.")
    return _backtest(df, ticker=ticker.upper())


# ──────────────────────────────────────────────
# NEWS SENTIMENT
# ──────────────────────────────────────────────

@app.get("/sentiment/{ticker}")
def get_sentiment(ticker: str):
    result = _bsnm.analyse(ticker.upper())
    return result.to_dict()


# ──────────────────────────────────────────────
# TICKER INTELLIGENCE — all-in-one
# ──────────────────────────────────────────────

@app.get("/intel/{ticker}")
def ticker_intel(ticker: str):
    """
    Aggregate all available intelligence for one ticker:
      ta, radar_alerts, india_entities, global_entities, company_graph_node
    Intended for the AI Intelligence page and chat context injection.
    """
    t = ticker.upper().replace(".NS", "")

    # TA signal (fast, cached)
    try:
        ta = _ta.analyse(t)
        ta_dict = ta.to_dict() if ta else None
    except Exception:
        ta_dict = None

    # Radar alerts for this ticker
    try:
        alerts = _radar.scan([t])
        alert_dicts = [a.to_dict() for a in alerts[:8]]
    except Exception:
        alert_dicts = []

    # India intelligence graph — search by ticker name
    try:
        india_hits = _india_orch.repo.search(t, limit=6)
        india_entities = [
            {"id": e.id, "name": e.canonical_name, "type": e.entity_type,
             "domain": e.domain, "description": getattr(e, "description", None),
             "attributes": e.attributes}
            for e in india_hits
        ]
    except Exception:
        india_entities = []

    # Global intelligence graph — search by ticker name
    try:
        global_hits = _global_orch.repo.search(t, limit=6)
        global_entities = [
            {"id": e.id, "name": e.canonical_name, "type": e.entity_type,
             "domain": e.domain, "description": getattr(e, "description", None),
             "attributes": e.attributes}
            for e in global_hits
        ]
    except Exception:
        global_entities = []

    # Finance graph node (company info)
    try:
        node = _graph.get_company_node(t)
        company = _repo._serialize_entity(node) if node else None
    except Exception:
        company = None

    return {
        "ticker":           t,
        "ta":               ta_dict,
        "radar_alerts":     alert_dicts,
        "india_entities":   india_entities,
        "global_entities":  global_entities,
        "company":          company,
    }


# ──────────────────────────────────────────────
# SIGNALS PAGE — top 15 with 5-level signal
# ──────────────────────────────────────────────

@app.get("/signals")
def get_signals(topk: int = Query(15, le=30)):
    """
    Returns top N tickers from the watchlist with a 5-level signal:
    STRONG BUY / WEAK BUY / HOLD / WEAK SELL / STRONG SELL.
    Sorted by signal conviction (|score| × confidence).
    """
    tickers = _portfolio["watchlist"][:40]
    sigs = _ta.analyse_many(tickers)

    result = []
    for ticker, sig in sigs.items():
        d = sig.to_dict()
        score = d.get("score", 0) or 0
        conf  = d.get("confidence", 0.5) or 0.5

        if score >= 2.0:
            signal = "STRONG BUY"
        elif score >= 1.0:
            signal = "WEAK BUY"
        elif score <= -2.0:
            signal = "STRONG SELL"
        elif score <= -1.0:
            signal = "WEAK SELL"
        else:
            signal = "HOLD"

        result.append({**d, "signal": signal, "conviction": round(abs(score) * conf, 4)})

    result.sort(key=lambda x: x["conviction"], reverse=True)
    return result[:topk]


# ──────────────────────────────────────────────
# PORTFOLIO INSIGHTS
# ──────────────────────────────────────────────

@app.get("/portfolio/insights")
def portfolio_insights():
    """
    Returns TA signals + radar alerts for every ticker in the user's portfolio.
    """
    holdings_tickers = list(_portfolio.get("holdings", {}).keys())
    watchlist_tickers = _portfolio.get("watchlist", [])[:20]
    # Union: holdings first, then watchlist fill to 20
    all_tickers = list(dict.fromkeys(holdings_tickers + watchlist_tickers))[:20]

    sigs    = _ta.analyse_many(all_tickers)
    alerts  = _radar.scan(all_tickers)
    alert_by_ticker: dict = {}
    for a in alerts:
        alert_by_ticker.setdefault(a.ticker, []).append(a.to_dict())

    items = []
    for t in all_tickers:
        sig = sigs.get(t)
        items.append({
            "ticker":   t,
            "ta":       sig.to_dict() if sig else None,
            "alerts":   alert_by_ticker.get(t, []),
            "quantity": _portfolio["holdings"].get(t, {}).get("quantity"),
            "avg_cost": _portfolio["holdings"].get(t, {}).get("avg_cost"),
        })
    return {"holdings": items, "portfolio": _portfolio}


# ──────────────────────────────────────────────
# OPPORTUNITY RADAR
# ──────────────────────────────────────────────

@app.get("/radar/alerts")
def radar_alerts(
    tickers: Optional[str] = Query(None, description="Comma-separated tickers; defaults to watchlist")
):
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    else:
        ticker_list = _portfolio["watchlist"][:30]

    alerts = _radar.scan(ticker_list)
    return [a.to_dict() for a in alerts[:50]]


@app.get("/radar/alerts/{ticker}")
def ticker_alerts(ticker: str):
    alerts = _radar.scan([ticker.upper()])
    return [a.to_dict() for a in alerts]


@app.get("/radar/compressed")
def radar_compressed(
    tickers: Optional[str] = Query(None, description="Comma-separated tickers; defaults to watchlist")
):
    """
    Scan the radar, then compress multiple alerts per ticker into one
    synthesised card per category (technical / news_market) via gpt-4o-mini.

    Returns:
      {
        "technical":   [{ticker, category, title, body, suggested_action,
                          direction, strength, evidence, alert_count}, ...],
        "news_market": [...]
      }
    """
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    else:
        ticker_list = _portfolio["watchlist"][:30]

    raw_alerts = _radar.scan(ticker_list)
    raw_dicts  = [a.to_dict() for a in raw_alerts]
    return compress_alerts(raw_dicts, OPENAI_API_KEY)


# ──────────────────────────────────────────────
# PORTFOLIO
# ──────────────────────────────────────────────

@app.get("/portfolio")
def get_portfolio():
    return _portfolio


class PortfolioUpdate(BaseModel):
    watchlist: Optional[List[str]] = None
    holdings:  Optional[dict]      = None


@app.post("/portfolio")
def update_portfolio(body: PortfolioUpdate):
    if body.watchlist is not None:
        _portfolio["watchlist"] = [t.upper() for t in body.watchlist]
        _vrishabh_rlm.rlm  # portfolio is passed by reference — already updated
    if body.holdings is not None:
        _portfolio["holdings"] = body.holdings
    return _portfolio


# ──────────────────────────────────────────────
# PIPELINE TRIGGERS
# ──────────────────────────────────────────────

@app.post("/pipeline/market")
def run_market_pipeline(
    tickers: Optional[str] = Query(None),
    fetch_info: bool = Query(True),
    force_prices: bool = Query(False, description="Force-refresh OHLCV parquet cache"),
):
    """
    Runs market pipeline synchronously (blocking). Also notifies the scheduler
    bus so SSE clients get the sync_done event.
    """
    from pipelines.market_data import fetch_all_ohlcv, NIFTY_500_TICKERS
    import time as _time
    ticker_list = [t.strip().upper() for t in tickers.split(",")] if tickers else None
    targets = ticker_list or NIFTY_500_TICKERS
    if force_prices:
        fetch_all_ohlcv(targets, force=True, max_workers=12)
    t0 = _time.time()
    _market.run(tickers=ticker_list, fetch_info=fetch_info)
    elapsed = round(_time.time() - t0, 2)
    _scheduler.bus.broadcast({"type": "sync_done", "pipeline": "market", "elapsed": elapsed,
                               "ts": __import__("datetime").datetime.now().isoformat(timespec="seconds")})
    return {"status": "done", "graph": _repo.summary()}


@app.post("/pipeline/news")
def run_news_pipeline(tickers: Optional[str] = Query(None)):
    import time as _time
    ticker_list = (
        [t.strip().upper() for t in tickers.split(",")]
        if tickers else _portfolio["watchlist"][:20]
    )
    t0 = _time.time()
    sentiments = _news.run(ticker_list)
    elapsed = round(_time.time() - t0, 2)
    _scheduler.bus.broadcast({"type": "sync_done", "pipeline": "news", "elapsed": elapsed,
                               "ts": __import__("datetime").datetime.now().isoformat(timespec="seconds")})
    return {"status": "done", "sentiments": sentiments}


# ──────────────────────────────────────────────
# VRISHABH CHAT — RLM Streaming
# ──────────────────────────────────────────────

import re as _re

_TICKER_RE = _re.compile(r'\b([A-Z][A-Z0-9\-]{1,9})\b')

def _extract_tickers(text: str) -> List[str]:
    """Heuristically extract NSE-style tickers mentioned in chat text."""
    known = set(NIFTY_500_TICKERS)
    # Also recognise common index shorthands
    known.update(["NIFTY", "SENSEX", "BANKNIFTY", "FINNIFTY", "MIDCAP"])
    found = []
    for m in _TICKER_RE.finditer(text):
        tok = m.group(1)
        if tok in known and tok not in found:
            found.append(tok)
    return found[:4]   # cap at 4 tickers per message

def _build_ticker_context(tickers: List[str]) -> str:
    """Fetch TA + radar for mentioned tickers and format as a context block."""
    if not tickers:
        return ""
    lines = ["── LIVE MARKET CONTEXT (do NOT cite these raw — synthesise naturally) ──"]
    sigs = _ta.analyse_many(tickers)
    alerts_all = _radar.scan(tickers)
    alert_by = {}
    for a in alerts_all:
        alert_by.setdefault(a.ticker, []).append(a)

    for t in tickers:
        sig = sigs.get(t)
        if sig:
            d = sig.to_dict()
            lines.append(
                f"{t}: action={d.get('suggested_action')} score={d.get('score')} "
                f"conf={d.get('confidence')} regime={d.get('regime')} "
                f"price=₹{d.get('last_close')} pct={d.get('pct_change')}%"
            )
        for a in alert_by.get(t, [])[:2]:
            ad = a.to_dict()
            lines.append(f"  radar: [{ad.get('category')}] {ad.get('title')} — {ad.get('body','')[:120]}")
    lines.append("─────────────────────────────────────────────────────────")
    return "\n".join(lines) + "\n\n"


class ChatRequest(BaseModel):
    question: str


class QuickChatRequest(BaseModel):
    question: str
    history:  Optional[List[Dict[str, str]]] = None  # [{role, content}]


@app.post("/chat")
def chat(body: ChatRequest):
    """Blocking chat endpoint."""
    answer = _vrishabh_rlm.ask(body.question)
    return {"answer": answer}


def _make_chat_stream(ask_fn):
    """Factory: returns an SSE generator that runs ask_fn in a background thread."""
    import time as _time

    def _event_generator():
        answer_holder: dict = {}
        error_holder:  dict = {}

        def _run():
            try:
                answer_holder["answer"] = ask_fn()
            except Exception as e:
                error_holder["error"] = str(e)

        with _rlm_log_lock:
            _rlm_log_buffer.clear()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        while thread.is_alive():
            with _rlm_log_lock:
                while _rlm_log_buffer:
                    msg = _rlm_log_buffer.pop(0)
                    yield f"data: {json.dumps({'type': 'log', 'msg': msg}, ensure_ascii=False)}\n\n"
            _time.sleep(0.1)

        thread.join()

        with _rlm_log_lock:
            for msg in _rlm_log_buffer:
                yield f"data: {json.dumps({'type': 'log', 'msg': msg}, ensure_ascii=False)}\n\n"
            _rlm_log_buffer.clear()

        if "error" in error_holder:
            yield f"data: {json.dumps({'type': 'error', 'msg': error_holder['error']}, ensure_ascii=False)}\n\n"
        else:
            answer = answer_holder.get("answer", "No response.")
            yield f"data: {json.dumps({'type': 'answer', 'msg': answer}, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"

    return _event_generator


@app.get("/chat/stream")
def chat_stream(q: str = Query(..., min_length=1)):
    """Deep chat — full RLM agentic loop with automatic ticker context injection."""
    ctx = _build_ticker_context(_extract_tickers(q))
    enriched = ctx + q if ctx else q
    return StreamingResponse(
        _make_chat_stream(lambda: _vrishabh_rlm.ask(enriched))(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/chat/stream/quick")
def chat_stream_quick(q: str = Query(..., min_length=1)):
    """Quick chat (no history) — with ticker context injection."""
    ctx = _build_ticker_context(_extract_tickers(q))
    enriched = ctx + q if ctx else q
    return StreamingResponse(
        _make_chat_stream(lambda: _vrishabh_rlm.ask_quick(enriched))(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _memory_context() -> str:
    """Build a memory prefix from data/memory.json to inject into chat requests."""
    try:
        mems = _load_memory()
        if not mems:
            return ""
        lines = ["── MEMORY (facts from past sessions — use as background context) ──"]
        for m in mems[-12:]:
            lines.append(f"  • {m['content']}")
        lines.append("─" * 52)
        return "\n".join(lines) + "\n\n"
    except Exception:
        return ""


@app.post("/chat/stream/quick")
def chat_stream_quick_post(body: QuickChatRequest):
    """Quick chat with conversation history — ticker context + memory injected."""
    history = (body.history or [])[-8:]
    ctx      = _build_ticker_context(_extract_tickers(body.question))
    mem      = _memory_context()
    enriched = mem + ctx + body.question
    return StreamingResponse(
        _make_chat_stream(lambda: _vrishabh_rlm.ask_quick(enriched, history=history))(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/chat/stream/agent")
def chat_stream_agent(body: QuickChatRequest):
    """
    Agent mode: per-ticker context PLUS a broad market overview (top signals + top radar
    from the watchlist) injected as context before calling ask_quick.
    Smarter than Quick, faster than Deep.
    """
    history  = (body.history or [])[-8:]
    q        = body.question
    tickers  = _extract_tickers(q)

    # Per-ticker enrichment (same as Quick)
    ticker_ctx = _build_ticker_context(tickers)

    # Broad market overview from watchlist
    watch = _portfolio["watchlist"][:15]
    ov = ["── MARKET OVERVIEW ──"]
    try:
        sigs = _ta.analyse_many(watch)
        rows = sorted(
            [
                (abs((d := sig.to_dict()).get("score", 0) or 0) * ((d.get("confidence") or 0.5)), t, d)
                for t, sig in sigs.items()
            ],
            reverse=True,
        )[:5]
        for _, t, d in rows:
            ov.append(
                f"  {t}: {d.get('suggested_action','?')} "
                f"score={d.get('score',0):.2f} regime={d.get('regime','?')}"
            )
    except Exception:
        pass
    try:
        alerts = sorted(
            _radar.scan(watch[:10]),
            key=lambda a: getattr(a, "strength", 0),
            reverse=True,
        )[:3]
        for a in alerts:
            ad = a.to_dict()
            ov.append(f"  [{ad.get('category','?')}] {a.ticker}: {ad.get('title','')}")
    except Exception:
        pass
    ov.append("─────────────────────────────────────────")
    overview = "\n".join(ov) + "\n\n"

    mem      = _memory_context()
    enriched = mem + ticker_ctx + overview + q
    return StreamingResponse(
        _make_chat_stream(lambda: _vrishabh_rlm.ask_quick(enriched, history=history))(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ──────────────────────────────────────────────
# MORNING BRIEF — streamed agent synthesis
# ──────────────────────────────────────────────

@app.get("/brief")
def get_brief():
    """
    Stream a morning market brief: top signals + radar alerts → LLM synthesis.
    Called on dashboard load and after market sync.
    """
    tickers = _portfolio["watchlist"][:25]
    sigs    = _ta.analyse_many(tickers)
    alerts  = _radar.scan(tickers[:15])

    # Top 6 signals by conviction
    sig_rows = []
    for ticker, sig in sigs.items():
        d        = sig.to_dict()
        score    = d.get("score", 0) or 0
        conf     = d.get("confidence", 0.5) or 0.5
        sig_rows.append((abs(score) * conf, ticker, d))
    sig_rows.sort(reverse=True)
    top_sigs = sig_rows[:6]

    # Top 4 radar alerts by strength
    alert_rows = sorted(
        alerts,
        key=lambda a: a.strength if hasattr(a, "strength") else 0,
        reverse=True,
    )[:4]

    sig_lines = "\n".join(
        f"  {t}: {d.get('suggested_action','?')} score={d.get('score',0):.2f} "
        f"regime={d.get('regime','?')}"
        for _, t, d in top_sigs
    ) or "  No data — run market sync first."

    alert_lines = "\n".join(
        f"  [{a.to_dict().get('category','?')}] {a.ticker}: {a.to_dict().get('title','')}"
        for a in alert_rows
    ) or "  No active alerts."

    prompt = (
        "You are Vrishabh writing your morning market brief for an Indian retail investor.\n\n"
        f"LIVE SIGNALS (top tickers by conviction):\n{sig_lines}\n\n"
        f"ACTIVE RADAR ALERTS:\n{alert_lines}\n\n"
        "Write a concise morning brief — 4 to 6 bullet points. Cover:\n"
        "• Overall market tone / regime today\n"
        "• 2–3 tickers worth watching and a one-line reason for each\n"
        "• One risk flag the investor should be aware of\n"
        "• One actionable idea or watchlist addition\n\n"
        "Be direct. Lead with the conclusion. Use ₹ for prices when relevant. "
        "No section headers — just bullets. Write like a sharp analyst."
    )

    return StreamingResponse(
        _make_chat_stream(lambda: _vrishabh_rlm.ask_quick(prompt))(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ──────────────────────────────────────────────
# BRIEF CACHE — pre-generated by scheduler
# ──────────────────────────────────────────────

@app.get("/brief/cached")
def get_brief_cached():
    """Return the last auto-generated brief (from scheduler), or null if none."""
    cache = _load_brief_cache()
    if not cache or "text" not in cache:
        return {"text": None}
    return cache

@app.post("/brief/generate")
def trigger_brief_generation():
    """Manually kick off a fresh brief generation in the background."""
    _scheduler.run_now("brief")
    return {"status": "generating"}


# ──────────────────────────────────────────────
# WATCH CONDITIONS
# ──────────────────────────────────────────────

class WatchRequest(BaseModel):
    ticker:      str
    metric:      str           # price | pct_change | ta_score | action
    operator:    str           # > < >= <= ==
    threshold:   float | str   # numeric or "BUY"/"SELL" for action
    description: str = ""


@app.get("/watch")
def list_watches():
    """Return all watch conditions (active + fired)."""
    return _load_watches()


@app.post("/watch")
def add_watch(body: WatchRequest):
    """Directly create a watch condition (UI path — agent uses create_watch tool)."""
    watches = _load_watches()
    w = {
        "id":          str(uuid.uuid4())[:8],
        "ticker":      body.ticker.upper().replace(".NS", ""),
        "metric":      body.metric,
        "operator":    body.operator,
        "threshold":   body.threshold,
        "description": body.description or f"{body.ticker} {body.metric} {body.operator} {body.threshold}",
        "created_at":  datetime.datetime.utcnow().isoformat(),
        "fired_at":    None,
        "active":      True,
    }
    watches.append(w)
    _save_watches(watches)
    return w


@app.delete("/watch/{watch_id}")
def delete_watch(watch_id: str):
    """Remove a watch condition by id."""
    watches = [w for w in _load_watches() if w["id"] != watch_id]
    _save_watches(watches)
    return {"status": "deleted"}


# ──────────────────────────────────────────────
# MEMORY
# ──────────────────────────────────────────────

@app.get("/memory")
def get_memory():
    """Return all persisted memory entries."""
    return _load_memory()


@app.delete("/memory/{mem_id}")
def delete_memory_entry(mem_id: str):
    """Remove a memory entry by id."""
    memories = [m for m in _load_memory() if m["id"] != mem_id]
    _save_memory(memories)
    return {"status": "deleted"}


# ──────────────────────────────────────────────
# PRICE HISTORY (for chart rendering)
# ──────────────────────────────────────────────

@app.get("/prices/{ticker}")
def get_prices(ticker: str, bars: int = Query(200, le=500)):
    from pipelines.market_data import fetch_ohlcv
    df = fetch_ohlcv(ticker.upper(), bars=bars)
    if df is None or df.empty:
        raise HTTPException(404, f"No price data for {ticker}.")
    df.index.name = "date"
    df.index = df.index.strftime("%Y-%m-%d")
    return df.reset_index().to_dict(orient="records")


# ──────────────────────────────────────────────
# GLOBAL GRAPH ENDPOINTS
# ──────────────────────────────────────────────

@app.get("/global/graph/data")
def global_graph_data():
    """Full global graph for vis.js (capped at 500 nodes)."""
    return _global_orch.repo.full_graph_data()


@app.get("/global/graph/summary")
def global_graph_summary():
    return _global_orch.summary()


@app.get("/global/search")
def global_search(q: str = Query(..., min_length=1), limit: int = Query(15, le=50)):
    results = _global_orch.repo.search(q, limit=limit)
    return [
        {
            "id":         e.id,
            "name":       e.canonical_name,
            "type":       e.entity_type,
            "domain":     e.domain,
            "aliases":    e.aliases,
            "attributes": e.attributes,
        }
        for e in results
    ]


@app.get("/global/entity/{entity_id}")
def global_entity(entity_id: str):
    e = _global_orch.repo.get_entity(entity_id)
    if not e:
        raise HTTPException(404, f"Entity {entity_id} not found.")
    return e.to_dict()


@app.get("/global/entity/{entity_id}/subgraph")
def global_entity_subgraph(entity_id: str, hops: int = Query(2, le=2)):
    e = _global_orch.repo.get_entity(entity_id)
    if not e:
        raise HTTPException(404, f"Entity {entity_id} not found.")
    return _global_orch.repo.entity_subgraph(entity_id, hops=hops)


@app.post("/pipeline/global")
def run_global_pipeline():
    """Trigger a full global graph ingestion run (slow — runs in background thread)."""
    def _run():
        try:
            stats = _global_orch.run()
            _rlm_log_cb(f"[GlobalGraph] Pipeline complete: {stats}")
        except Exception as e:
            _rlm_log_cb(f"[GlobalGraph] Pipeline error: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"status": "started", "message": "Global graph pipeline running in background."}


# ──────────────────────────────────────────────
# INDIA INTELLIGENCE GRAPH ENDPOINTS
# ──────────────────────────────────────────────

@app.get("/india/graph/data")
def india_graph_data():
    """Full India intelligence graph for vis.js (capped at 500 nodes)."""
    return _india_orch.repo.full_graph_data()


@app.get("/india/graph/summary")
def india_graph_summary():
    return _india_orch.summary()


@app.get("/india/search")
def india_search(q: str = Query(..., min_length=1), limit: int = Query(15, le=50)):
    results = _india_orch.repo.search(q, limit=limit)
    return [
        {
            "id":         e.id,
            "name":       e.canonical_name,
            "type":       e.entity_type,
            "domain":     e.domain,
            "aliases":    e.aliases,
            "attributes": e.attributes,
        }
        for e in results
    ]


@app.get("/india/entity/{entity_id}")
def india_entity(entity_id: str):
    e = _india_orch.repo.get_entity(entity_id)
    if not e:
        raise HTTPException(404, f"Entity {entity_id} not found in India graph.")
    return e.to_dict()


@app.get("/india/entity/{entity_id}/subgraph")
def india_entity_subgraph(entity_id: str, hops: int = Query(2, le=2)):
    e = _india_orch.repo.get_entity(entity_id)
    if not e:
        raise HTTPException(404, f"Entity {entity_id} not found in India graph.")
    return _india_orch.repo.entity_subgraph(entity_id, hops=hops)


@app.post("/pipeline/india")
def run_india_pipeline():
    """Trigger India intelligence graph ingestion (background)."""
    def _run():
        try:
            stats = _india_orch.run()
            _rlm_log_cb(f"[IndiaGraph] Pipeline complete: {stats}")
        except Exception as e:
            _rlm_log_cb(f"[IndiaGraph] Pipeline error: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"status": "started", "message": "India graph pipeline running in background."}
