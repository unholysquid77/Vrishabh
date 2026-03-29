# Vrishabh / Vidur — Impact Model

## The Problem We're Solving

Indian retail investors (45% of NSE daily volume, ~90M active DEMAT accounts) have no intelligent co-pilot:

| Tool | Cost | What's missing |
|------|------|---------------|
| Bloomberg / Refinitiv terminal | ₹20,000–₹50,000/month | Unaffordable for retail |
| SEBI-registered advisor | ₹10,000–₹30,000/yr + commissions | Conflicted, not personalized |
| Free screeners (Screener.in, TradingView) | Free | Raw data, no synthesis |
| Robo-advisors | 0.5–1% AUM/yr | Passive allocation, no tactical |

**Vidur fills this gap**: an always-on, proactive AI analyst that thinks like a research desk but costs nothing.

---

## Quantified Impact Estimates

### Time Savings

A typical active retail investor spends ~45–90 min/day on market research:

| Activity | Current time | With Vidur | Saving |
|----------|-------------|-----------|--------|
| Morning market scan | 20 min | 2 min (read brief) | 18 min |
| Signal discovery | 15 min | 0 (radar auto-surfaces) | 15 min |
| News → impact mapping | 20 min | 5 min (ask agent) | 15 min |
| Research before trade | 30 min | 8 min (deep chat) | 22 min |
| **Total** | **85 min/day** | **15 min/day** | **~82% reduction** |

At ₹500/hr opportunity cost: **₹583/day saved per user = ₹1.75L/year**.

### Decision Quality

Suvarn TA engine — signal accuracy benchmarks:
*(Backtest data to be added — see placeholder below)*

Conservative estimate based on architecture (regime-aware signals, 300-bar lookback, 5-level conviction scoring):

| Metric | Estimate | Basis |
|--------|----------|-------|
| Signal win rate improvement vs random | +12–18% | Regime-filtered vs unfiltered signals |
| False signal reduction (choppy market) | ~40% | Regime detection suppresses signals in sideways regimes |
| Average holding period optimization | +15% | Exit signals calibrated to regime transitions |

At ₹5L average portfolio, 2% improvement in returns = **₹10,000/year per user**.

### Access Democratization

India's wealth management advice gap:
- ~90M active DEMAT holders
- <2M have access to quality research (HNI clients of brokerages)
- **88M underserved** — Vidur's addressable market

---

## Suvarn Backtest Data

*(Section placeholder — backtest results to be provided)*

Suvarn is the TA engine powering Vidur's signal layer. Key capabilities:
- **Regime detection**: Identifies trending, ranging, and reverting market states
- **5-level signal scoring**: Tracks conviction across momentum, volume, pattern, and support/resistance dimensions
- **Pattern recognition**: 20+ candlestick and chart patterns via PatternPy + custom implementations
- **300-bar lookback**: Sufficient history for meaningful trend and cycle analysis

**Backtest summary will be inserted here.** Expected format:

| Strategy | Universe | Period | Win Rate | Avg Return | Max Drawdown | Sharpe |
|----------|----------|--------|----------|------------|--------------|--------|
| Suvarn BUY signals (score > 0.40) | Nifty 500 | — | — | — | — | — |
| Suvarn SELL signals (score < -0.40) | Nifty 500 | — | — | — | — | — |
| Full Suvarn system | Nifty 50 | — | — | — | — | — |

---

## Business Model — Vidur Free + Suvarn SaaS

### Why Free?

Vidur (the platform) is free at launch. The value proposition is access democratization: the 88M retail investors who can't afford a terminal deserve the same quality of analysis as an HNI client. Ad-supported or freemium tiers are possible later, but the hackathon pitch is **zero cost to the user**.

### Suvarn as SaaS — The Monetization Layer

Suvarn is the proprietary TA engine. While Vidur includes a local fallback TA engine, the full Suvarn system with:
- Live intraday signal streaming
- Backtested regime parameters (not publicly available)
- Angel One / broker integration for auto-alerts
- Portfolio-level signal aggregation

...is offered as an API subscription:

| Tier | Price | Included |
|------|-------|---------|
| **Free** (via Vidur) | ₹0 | EOD signals, 300-bar TA, basic regime |
| **Pro** | ₹499/month | Live signals, all 20+ patterns, email/SMS alerts |
| **Algo** | ₹1,999/month | API access, backtesting API, broker webhooks |
| **Institutional** | Custom | White-label, bulk tickers, dedicated infra |

### Unit Economics

| Metric | Assumption | Value |
|--------|------------|-------|
| Target Vidur MAU (Year 1) | Hackathon → viral via ET audience | 10,000 |
| Suvarn Pro conversion rate | 3% of engaged users | 300 |
| Suvarn Algo conversion rate | 0.5% | 50 |
| MRR at Year 1 target | 300 × ₹499 + 50 × ₹1,999 | ₹2.5L/month |
| ARR target | — | **₹30L/year** |
| CAC | Near zero (ET distribution channel) | ₹0 |
| LTV (Pro, 18-month avg) | 18 × ₹499 | ₹8,982 |

### Competitive Moat

1. **India-first knowledge graph**: Paqshi's India intel graph (conglomerates, RBI/SEBI policy, sector relationships) is hand-curated. Competitors use generic global LLMs that hallucinate Indian market context.
2. **Proactive agent**: Vrishabh acts before the user asks. No competitor in the Indian retail space has autonomous brief generation + watch condition monitoring.
3. **TA + fundamental synthesis**: Suvarn TA + Paqshi macro graph combination is unique. Most tools are either TA-only or news-only.
4. **Cost**: Zero marginal cost to the investor. Monetization via the power user (algo traders, serious retail).

---

## Rubric Alignment

| Rubric criterion | How Vidur addresses it |
|-----------------|----------------------|
| **Signal quality** | Suvarn TA engine: regime-aware, 5-level conviction, 300-bar lookback. Signals filtered by regime (no BUY signals in bearish regimes). |
| **3+ sequential agentic steps** | Agent mode: (1) ticker extraction → (2) per-ticker TA context → (3) broad market overview → (4) enriched LLM call. Deep mode: up to 7 tool-call rounds with live trace. |
| **Portfolio personalization** | Watchlist-aware enrichment, persistent memory injection, natural-language watch conditions per user. |
| **Autonomous operation** | Scheduler generates briefs every 3h during market hours. Watch conditions fire SSE alerts without user polling. System acts first. |
| **Explainability** | Deep mode streams live tool trace (🔍🕸📊📡🧠). Users see exactly what data informed the answer. |

---

## Risk Factors

| Risk | Mitigation |
|------|-----------|
| OpenAI API cost at scale | GPT-4o-mini for bulk sentiment; GPT-4o only for final synthesis |
| yfinance rate limits | 2-minute cache; Angel One integration for production |
| NewsData.io 200 req/day (free tier) | Prioritize watchlist tickers; upgrade at scale |
| SEBI regulations on AI advice | Disclaimer: "informational only, not SEBI-registered advice" |
| Graph data staleness | Paqshi pipelines designed for daily refresh; manual curation for structural relationships |
