"""
VrishabScheduler — backend-owned sync scheduler.

Runs all pipelines on a fixed schedule regardless of whether the UI is open.
Broadcasts status events to connected SSE clients via asyncio queues.

Intervals (configurable via env vars):
  VIDUR_MARKET_INTERVAL   seconds, default  120   (2 min)
  VIDUR_NEWS_INTERVAL     seconds, default 3600   (1 hr)
  VIDUR_GRAPH_INTERVAL    seconds, default 21600  (6 hr)
  VIDUR_INSIGHTS_INTERVAL seconds, default 3600   (1 hr)
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set

# ──────────────────────────────────────────────────────────────────
# DATA HELPERS  (shared with server.py via import)
# ──────────────────────────────────────────────────────────────────

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_IST      = datetime.timedelta(hours=5, minutes=30)

# Brief cache -------------------------------------------------------

def _load_brief_cache() -> dict:
    path = os.path.join(_DATA_DIR, "brief_cache.json")
    try:
        if os.path.exists(path):
            return json.loads(open(path, encoding="utf-8").read())
    except Exception:
        pass
    return {}

def _save_brief_cache(cache: dict):
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(os.path.join(_DATA_DIR, "brief_cache.json"), "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

# Watch conditions --------------------------------------------------

def _load_watches() -> list:
    path = os.path.join(_DATA_DIR, "watches.json")
    try:
        if os.path.exists(path):
            return json.loads(open(path).read())
    except Exception:
        pass
    return []

def _save_watches(watches: list):
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(os.path.join(_DATA_DIR, "watches.json"), "w") as f:
        json.dump(watches, f, indent=2)

# Memory ------------------------------------------------------------

def _load_memory() -> list:
    path = os.path.join(_DATA_DIR, "memory.json")
    try:
        if os.path.exists(path):
            return json.loads(open(path, encoding="utf-8").read())
    except Exception:
        pass
    return []

def _save_memory(memories: list):
    os.makedirs(_DATA_DIR, exist_ok=True)
    with open(os.path.join(_DATA_DIR, "memory.json"), "w", encoding="utf-8") as f:
        json.dump(memories[-50:], f, ensure_ascii=False, indent=2)

# ──────────────────────────────────────────────────────────────────
# INTERVAL DEFAULTS  (overridable via env)
# ──────────────────────────────────────────────────────────────────

MARKET_INTERVAL   = int(os.getenv("VIDUR_MARKET_INTERVAL",    "120"))
NEWS_INTERVAL     = int(os.getenv("VIDUR_NEWS_INTERVAL",     "3600"))
GRAPH_INTERVAL    = int(os.getenv("VIDUR_GRAPH_INTERVAL",   "21600"))
INSIGHTS_INTERVAL = int(os.getenv("VIDUR_INSIGHTS_INTERVAL", "3600"))


# ──────────────────────────────────────────────────────────────────
# SSE BROADCAST LAYER
# ──────────────────────────────────────────────────────────────────

class _SSEBus:
    """
    Thread-safe SSE event bus.

    Scheduler threads call  broadcast(event_dict).
    Async SSE generators    call  subscribe() / unsubscribe().
    """

    def __init__(self):
        self._lock:    threading.Lock         = threading.Lock()
        self._queues:  Set[asyncio.Queue]     = set()
        self._loop:    Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Called once from the asyncio startup event to capture the event loop."""
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=64)
        with self._lock:
            self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        with self._lock:
            self._queues.discard(q)

    def broadcast(self, event: dict):
        """
        Called from any thread (scheduler). Enqueues the event for all
        connected SSE clients using the asyncio event loop.
        """
        if not self._loop:
            return
        payload = _fmt(event)
        with self._lock:
            dead = set()
            for q in self._queues:
                try:
                    self._loop.call_soon_threadsafe(q.put_nowait, payload)
                except Exception:
                    dead.add(q)
            self._queues -= dead


def _fmt(event: dict) -> str:
    """Format a dict as an SSE data line."""
    import json
    return "data: " + json.dumps(event, default=str) + "\n\n"


def _ts() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


# ──────────────────────────────────────────────────────────────────
# SYNC STATE
# ──────────────────────────────────────────────────────────────────

class SyncState:
    """Tracks last-run time, status, and elapsed time for every pipeline."""

    def __init__(self):
        self._lock = threading.Lock()
        self._state: Dict[str, dict] = {}

    def mark_start(self, pipeline: str):
        with self._lock:
            self._state[pipeline] = {
                "status": "running",
                "started_at": _ts(),
                "finished_at": None,
                "elapsed": None,
                "error": None,
            }

    def mark_done(self, pipeline: str, elapsed: float):
        with self._lock:
            s = self._state.get(pipeline, {})
            s.update(status="ok", finished_at=_ts(), elapsed=round(elapsed, 2), error=None)
            self._state[pipeline] = s

    def mark_error(self, pipeline: str, elapsed: float, error: str):
        with self._lock:
            s = self._state.get(pipeline, {})
            s.update(status="error", finished_at=_ts(), elapsed=round(elapsed, 2), error=error)
            self._state[pipeline] = s

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._state)


# ──────────────────────────────────────────────────────────────────
# SCHEDULER
# ──────────────────────────────────────────────────────────────────

class VrishabScheduler:
    """
    Background scheduler that owns all periodic data syncs.

    Usage (in server.py):
        sched = VrishabScheduler(market=_market, news=_news, ...)
        sched.set_loop(asyncio.get_event_loop())   # in startup event
        sched.start()                               # launches daemon threads
        sched.run_now("market")                     # optional manual trigger
    """

    def __init__(
        self,
        market,           # MarketDataPipeline
        news,             # NewsPipeline
        india_orch,       # IndiaGraphOrchestrator
        global_orch,      # GlobalGraphOrchestrator
        portfolio: dict,
        ta=None,
        bsnm=None,
        radar=None,
        rlm=None,         # VrishabRLM — for autonomous brief generation
        insights_topk: int = 3,
    ):
        self._market      = market
        self._news        = news
        self._india_orch  = india_orch
        self._global_orch = global_orch
        self._portfolio   = portfolio
        self._ta          = ta
        self._bsnm        = bsnm
        self._radar       = radar
        self._rlm         = rlm
        self._topk        = insights_topk

        self.bus   = _SSEBus()
        self.state = SyncState()

        self._stop   = threading.Event()
        self._market_macro_cache: Optional[dict] = None   # latest macro for SSE push

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self.bus.set_loop(loop)

    # ── public API ────────────────────────────────────────────────

    def start(self):
        """Launch all background threads. Call once from server startup."""
        # Startup sync always runs regardless of market hours (populates cache)
        self._run_market()
        # Periodic sync checks market hours before running
        self._launch("market",   self._market_loop,   MARKET_INTERVAL,   run_now=False)
        self._launch("news",     self._news_loop,     NEWS_INTERVAL,     run_now=True)
        self._launch("graphs",   self._graph_loop,    GRAPH_INTERVAL,    run_now=False)
        self._launch("insights", self._insights_loop, INSIGHTS_INTERVAL, run_now=False)
        # Brief: dedicated loop that auto-generates during market hours
        threading.Thread(target=self._brief_loop, daemon=True, name="brief").start()
        # Heartbeat thread (keeps SSE connections alive)
        threading.Thread(target=self._heartbeat_loop, daemon=True, name="hb").start()
        print(
            f"[Scheduler] Started — market every {MARKET_INTERVAL}s (NSE hours only), "
            f"news every {NEWS_INTERVAL}s, graphs every {GRAPH_INTERVAL}s, "
            f"insights every {INSIGHTS_INTERVAL}s"
        )

    def run_now(self, pipeline: str):
        """Manually trigger a pipeline run in a new daemon thread."""
        fn = {
            "market":   self._run_market,
            "news":     self._run_news,
            "india":    self._run_india,
            "global":   self._run_global,
            "graphs":   self._run_graphs,
            "insights": self._run_insights,
            "brief":    self._run_brief,
        }.get(pipeline)
        if fn:
            threading.Thread(target=fn, daemon=True, name=f"manual-{pipeline}").start()

    def get_status(self) -> dict:
        return {
            "pipelines": self.state.snapshot(),
            "intervals": {
                "market_s":   MARKET_INTERVAL,
                "news_s":     NEWS_INTERVAL,
                "graphs_s":   GRAPH_INTERVAL,
                "insights_s": INSIGHTS_INTERVAL,
            },
        }

    # ── loop wrappers ─────────────────────────────────────────────

    def _launch(self, name: str, loop_fn: Callable, interval: int, run_now: bool):
        def _runner():
            if run_now:
                loop_fn()
            while not self._stop.is_set():
                self._stop.wait(timeout=interval)
                if not self._stop.is_set():
                    loop_fn()
        threading.Thread(target=_runner, daemon=True, name=name).start()

    def _heartbeat_loop(self):
        while not self._stop.is_set():
            self.bus.broadcast({"type": "heartbeat", "ts": _ts(), "status": self.state.snapshot()})
            self._stop.wait(timeout=30)

    # ── pipeline runners ──────────────────────────────────────────

    def _run_market(self):
        pipeline = "market"
        tickers  = self._portfolio.get("watchlist", [])[:40]
        self.state.mark_start(pipeline)
        self.bus.broadcast({"type": "sync_start", "pipeline": pipeline, "ts": _ts()})
        t0 = time.time()
        try:
            self._market.run(tickers=tickers, fetch_info=False)
            elapsed = time.time() - t0
            self.state.mark_done(pipeline, elapsed)
            self.bus.broadcast({
                "type": "sync_done", "pipeline": pipeline,
                "elapsed": round(elapsed, 2), "ts": _ts(),
            })
            # Broadcast fresh macro data so the UI can update immediately
            # We call the server's /macro route logic directly via its helper
            try:
                import yfinance as yf  # type: ignore
                _MACRO_SYMBOLS = {
                    "nifty50":   ("^NSEI",    "Nifty 50"),
                    "banknifty": ("^NSEBANK", "Bank Nifty"),
                    "sensex":    ("^BSESN",   "Sensex"),
                    "usdinr":    ("USDINR=X", "USD/INR"),
                }
                macro: dict = {}
                for key, (sym, _label) in _MACRO_SYMBOLS.items():
                    try:
                        tk   = yf.Ticker(sym)
                        info = tk.fast_info
                        price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
                        prev  = getattr(info, "previous_close", None)
                        pct   = round((price - prev) / prev * 100, 2) if price and prev else None
                        if price:
                            macro[key] = {"price": round(price, 2), "pct_change": pct}
                    except Exception:
                        pass
                if macro:
                    self._market_macro_cache = macro
                    self.bus.broadcast({"type": "market_data", "data": macro, "ts": _ts()})
            except Exception:
                pass
            # Check watch conditions against fresh TA data
            try:
                self._check_watches()
            except Exception as _we:
                print(f"[Scheduler/watches] Error: {_we}")
            print(f"[Scheduler/market] Done in {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - t0
            self.state.mark_error(pipeline, elapsed, str(e))
            self.bus.broadcast({"type": "sync_error", "pipeline": pipeline, "error": str(e), "ts": _ts()})
            print(f"[Scheduler/market] Error: {e}")

    def _market_loop(self):
        # NSE hours: Mon–Fri 09:00–16:00 IST — skip sync outside market hours
        now_ist = datetime.datetime.utcnow() + _IST
        if now_ist.weekday() >= 5 or not (9 <= now_ist.hour < 16):
            return
        self._run_market()

    def _run_news(self):
        pipeline = "news"
        tickers  = self._portfolio.get("watchlist", [])[:20]
        self.state.mark_start(pipeline)
        self.bus.broadcast({"type": "sync_start", "pipeline": pipeline, "ts": _ts()})
        t0 = time.time()
        try:
            self._news.run(tickers)
            elapsed = time.time() - t0
            self.state.mark_done(pipeline, elapsed)
            self.bus.broadcast({"type": "sync_done", "pipeline": pipeline, "elapsed": round(elapsed, 2), "ts": _ts()})
            print(f"[Scheduler/news] Done in {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - t0
            self.state.mark_error(pipeline, elapsed, str(e))
            self.bus.broadcast({"type": "sync_error", "pipeline": pipeline, "error": str(e), "ts": _ts()})
            print(f"[Scheduler/news] Error: {e}")

    def _news_loop(self):
        self._run_news()

    def _run_india(self):
        pipeline = "india"
        self.state.mark_start(pipeline)
        self.bus.broadcast({"type": "sync_start", "pipeline": pipeline, "ts": _ts()})
        t0 = time.time()
        try:
            self._india_orch.build()
            elapsed = time.time() - t0
            self.state.mark_done(pipeline, elapsed)
            self.bus.broadcast({"type": "sync_done", "pipeline": pipeline, "elapsed": round(elapsed, 2), "ts": _ts()})
            print(f"[Scheduler/india] Done in {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - t0
            self.state.mark_error(pipeline, elapsed, str(e))
            self.bus.broadcast({"type": "sync_error", "pipeline": pipeline, "error": str(e), "ts": _ts()})
            print(f"[Scheduler/india] Error: {e}")

    def _run_global(self):
        pipeline = "global"
        self.state.mark_start(pipeline)
        self.bus.broadcast({"type": "sync_start", "pipeline": pipeline, "ts": _ts()})
        t0 = time.time()
        try:
            self._global_orch.build()
            elapsed = time.time() - t0
            self.state.mark_done(pipeline, elapsed)
            self.bus.broadcast({"type": "sync_done", "pipeline": pipeline, "elapsed": round(elapsed, 2), "ts": _ts()})
            print(f"[Scheduler/global] Done in {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - t0
            self.state.mark_error(pipeline, elapsed, str(e))
            self.bus.broadcast({"type": "sync_error", "pipeline": pipeline, "error": str(e), "ts": _ts()})
            print(f"[Scheduler/global] Error: {e}")

    def _run_graphs(self):
        self._run_india()
        self._run_global()

    def _graph_loop(self):
        self._run_graphs()

    def _run_insights(self):
        if not (self._ta and self._bsnm and self._radar):
            return
        pipeline = "insights"
        self.state.mark_start(pipeline)
        self.bus.broadcast({"type": "sync_start", "pipeline": pipeline, "ts": _ts()})
        t0 = time.time()
        try:
            from llm_insights import run_llm_insights  # type: ignore
            tickers  = self._portfolio.get("watchlist", [])[:40]
            sigs     = self._ta.analyse_many(tickers)
            enriched = sorted(
                [s for s in sigs.values() if s.pct_change is not None],
                key=lambda s: s.pct_change or 0, reverse=True,
            )
            topk     = self._topk
            gainers  = [s.ticker for s in enriched[:topk]]
            losers   = [s.ticker for s in enriched[-topk:]]
            seen: set = set()
            all_t = []
            for t in gainers + losers:
                if t not in seen:
                    seen.add(t)
                    all_t.append(t)
            sig_map  = {s.ticker: s.to_dict() for s in sigs.values()}
            result   = run_llm_insights(all_t, self._ta, self._bsnm, self._radar, sig_map)
            elapsed  = time.time() - t0
            self.state.mark_done(pipeline, elapsed)
            self.bus.broadcast({
                "type": "sync_done", "pipeline": pipeline,
                "elapsed": round(elapsed, 2), "ts": _ts(),
                "data": result,   # push insights to connected clients
            })
            print(f"[Scheduler/insights] Done in {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - t0
            self.state.mark_error(pipeline, elapsed, str(e))
            self.bus.broadcast({"type": "sync_error", "pipeline": pipeline, "error": str(e), "ts": _ts()})
            print(f"[Scheduler/insights] Error: {e}")

    def _insights_loop(self):
        self._run_insights()

    # ── watch condition checker ────────────────────────────────────

    def _check_watches(self):
        """Evaluate all active watch conditions against fresh TA data; fire if met."""
        if not self._ta:
            return
        watches = _load_watches()
        active  = [w for w in watches if w.get("active")]
        if not active:
            return

        tickers = list({w["ticker"] for w in active})
        try:
            sigs = self._ta.analyse_many(tickers)
        except Exception:
            return

        changed = False
        for w in watches:
            if not w.get("active"):
                continue
            sig = sigs.get(w["ticker"])
            if not sig:
                continue
            d      = sig.to_dict()
            metric = w["metric"]
            op     = w["operator"]
            thr    = w["threshold"]

            if metric == "price":
                current = d.get("last_close")
            elif metric == "pct_change":
                current = d.get("pct_change")
            elif metric == "ta_score":
                current = d.get("score")
            elif metric == "action":
                current = (d.get("suggested_action") or "").upper()
            else:
                continue

            if current is None:
                continue

            try:
                if metric == "action":
                    fired = (op == "==" and current == str(thr).upper())
                else:
                    if   op == ">":  fired = current > thr
                    elif op == "<":  fired = current < thr
                    elif op == ">=": fired = current >= thr
                    elif op == "<=": fired = current <= thr
                    elif op == "==": fired = abs(current - thr) < 0.01
                    else:            fired = False
            except Exception:
                continue

            if fired:
                w["fired_at"] = datetime.datetime.utcnow().isoformat()
                w["active"]   = False
                changed       = True
                self.bus.broadcast({
                    "type":          "watch_fired",
                    "watch_id":      w["id"],
                    "ticker":        w["ticker"],
                    "description":   w.get("description", ""),
                    "current_value": current,
                    "ts":            _ts(),
                })
                print(f"[Scheduler/watch] FIRED: {w.get('description')}")

        if changed:
            _save_watches(watches)

    # ── autonomous brief ───────────────────────────────────────────

    def _brief_loop(self):
        """Generate a brief every ~3h during IST market hours; on first startup too."""
        # On startup: generate immediately if no cached brief exists
        if not _load_brief_cache():
            try:
                self._run_brief()
            except Exception as e:
                print(f"[Scheduler/brief] startup error: {e}")
        while not self._stop.is_set():
            self._stop.wait(timeout=120)   # check every 2 min
            if self._stop.is_set():
                break
            try:
                self._maybe_generate_brief()
            except Exception as e:
                print(f"[Scheduler/brief] loop error: {e}")

    def _maybe_generate_brief(self):
        if not self._rlm:
            return
        now_ist = datetime.datetime.utcnow() + _IST
        # Only during market hours (9:00–17:00 IST)
        if not (9 <= now_ist.hour < 17):
            return
        cache = _load_brief_cache()
        if cache:
            try:
                last = datetime.datetime.fromisoformat(cache["generated_at"])
                if (datetime.datetime.utcnow() - last).total_seconds() < 3 * 3600:
                    return   # Generated within last 3 hours — skip
            except Exception:
                pass
        self._run_brief()

    def _run_brief(self):
        """Generate morning brief and persist to data/brief_cache.json."""
        if not (self._rlm and self._ta and self._radar):
            return
        pipeline = "brief"
        self.state.mark_start(pipeline)
        self.bus.broadcast({"type": "sync_start", "pipeline": pipeline, "ts": _ts()})
        t0 = time.time()
        try:
            tickers = self._portfolio.get("watchlist", [])[:25]
            sigs    = self._ta.analyse_many(tickers)
            alerts  = self._radar.scan(tickers[:15])

            sig_rows = sorted(
                [
                    (abs((d := sig.to_dict()).get("score", 0) or 0) * ((d.get("confidence") or 0.5)), t, d)
                    for t, sig in sigs.items()
                ],
                reverse=True,
            )[:6]
            alert_rows = sorted(alerts, key=lambda a: getattr(a, "strength", 0), reverse=True)[:4]

            sig_lines = "\n".join(
                f"  {t}: {d.get('suggested_action','?')} score={d.get('score',0):.2f} regime={d.get('regime','?')}"
                for _, t, d in sig_rows
            ) or "  No data yet."

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

            text    = self._rlm.ask_quick(prompt)
            now_utc = datetime.datetime.utcnow()
            now_ist = now_utc + _IST
            cache   = {
                "text":             text,
                "generated_at":     now_utc.isoformat(),
                "generated_at_ist": now_ist.strftime("%I:%M %p"),
            }
            _save_brief_cache(cache)

            elapsed = time.time() - t0
            self.state.mark_done(pipeline, elapsed)
            self.bus.broadcast({
                "type": "sync_done", "pipeline": pipeline,
                "elapsed": round(elapsed, 2), "ts": _ts(),
            })
            print(f"[Scheduler/brief] Generated in {elapsed:.1f}s")
        except Exception as e:
            elapsed = time.time() - t0
            self.state.mark_error(pipeline, elapsed, str(e))
            self.bus.broadcast({"type": "sync_error", "pipeline": pipeline, "error": str(e), "ts": _ts()})
            print(f"[Scheduler/brief] Error: {e}")
