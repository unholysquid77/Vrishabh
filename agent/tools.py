"""
VrishabRLM Tool Functions
These are injected into the RLM REPL as Python callables.
The RLM writes code that calls them to reason over market data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from graph import GraphRepository
    from suvarn_client import SuvarnTAClient as TAEngine, SuvarnBSNMClient as BSNMEngine
    from radar.radar import OpportunityRadar


def build_tools(
    repo:         "GraphRepository",
    ta:           "TAEngine",
    bsnm:         "BSNMEngine",
    radar:        "OpportunityRadar",
    portfolio:    Optional[Dict] = None,
    global_repo=  None,    # GlobalGraphRepository (optional)
    india_repo=   None,    # IndiaGraphRepository  (optional)
) -> dict:
    """
    Returns the tools dict to pass as custom_tools to RLM.
    Each value is either a callable or a {tool, description} dict.
    """

    graph = repo.graph

    # ──────────────────────────────────────────
    # COMPANY INFO
    # ──────────────────────────────────────────

    def get_company_info(ticker: str) -> dict:
        """
        Get stored metadata for a company from the knowledge graph.
        Returns: name, sector, industry, market_cap, description, and graph id.
        """
        ticker = ticker.upper().replace(".NS", "")
        node   = graph.get_company_node(ticker)
        if not node:
            return {"error": f"Company {ticker} not found in graph. Try search_companies() first."}
        return {
            "ticker":      node.ticker,
            "name":        node.canonical_name,
            "sector":      node.attributes.get("sector"),
            "industry":    node.attributes.get("industry"),
            "market_cap_cr": node.attributes.get("market_cap"),
            "exchange":    node.attributes.get("exchange"),
            "description": node.description,
            "graph_id":    node.id,
        }

    # ──────────────────────────────────────────
    # TECHNICAL SIGNALS
    # ──────────────────────────────────────────

    def get_technical_signals(ticker: str) -> dict:
        """
        Get technical analysis signals for a stock.
        Returns: score, regime, suggested_action, confidence,
                 last_close, masala_scores, patterns, support, resistance.
        """
        ticker = ticker.upper().replace(".NS", "")
        sig    = ta.analyse(ticker)
        if not sig:
            return {"error": f"Insufficient data for {ticker}. Needs 200+ days of price history."}
        return sig.to_dict()

    # ──────────────────────────────────────────
    # NEWS SENTIMENT
    # ──────────────────────────────────────────

    def get_news_sentiment(ticker: str) -> dict:
        """
        Get business news sentiment score for a stock.
        Returns: score (-1 to +1), headline_summary, top_headlines, articles_found.
        """
        ticker = ticker.upper().replace(".NS", "")
        result = bsnm.analyse(ticker)
        return result.to_dict()

    # ──────────────────────────────────────────
    # INSIDER ACTIVITY
    # ──────────────────────────────────────────

    def get_insider_activity(ticker: str) -> list:
        """
        Get recent insider/bulk/block trades for a stock from the knowledge graph.
        Returns list of trade dicts: trade_type, trader_name, quantity, price, value_crores, trade_date.
        """
        from graph.entities import EntityType
        ticker  = ticker.upper().replace(".NS", "")
        company = graph.get_company_node(ticker)
        if not company:
            return []

        trades = []
        for rel in graph.get_relations_from(company.id):
            node = graph.get_node(rel.to_node_id)
            if node and node.ontology_type == EntityType.INSIDER_TRADE:
                trades.append({
                    "trade_type":   node.attributes.get("trade_type"),
                    "trader_name":  node.attributes.get("trader_name"),
                    "quantity":     node.attributes.get("quantity"),
                    "price":        node.attributes.get("price"),
                    "value_crores": node.attributes.get("value_crores"),
                    "trade_date":   node.attributes.get("trade_date"),
                })

        return sorted(trades, key=lambda x: x.get("trade_date") or "", reverse=True)[:10]

    # ──────────────────────────────────────────
    # FILINGS
    # ──────────────────────────────────────────

    def get_filings(ticker: str) -> list:
        """
        Get recent corporate filings for a stock from the knowledge graph.
        Returns list of filing dicts: filing_type, period, summary, key_metrics.
        """
        from graph.entities import EntityType
        ticker  = ticker.upper().replace(".NS", "")
        company = graph.get_company_node(ticker)
        if not company:
            return []

        filings = []
        for rel in graph.get_relations_from(company.id):
            node = graph.get_node(rel.to_node_id)
            if node and node.ontology_type == EntityType.FILING:
                filings.append({
                    "filing_type": node.attributes.get("filing_type"),
                    "period":      node.attributes.get("period"),
                    "summary":     node.attributes.get("summary"),
                    "key_metrics": node.attributes.get("key_metrics", {}),
                    "filed_at":    node.attributes.get("filed_at"),
                })
        return sorted(filings, key=lambda x: x.get("filed_at") or "", reverse=True)[:5]

    # ──────────────────────────────────────────
    # RADAR ALERTS
    # ──────────────────────────────────────────

    def get_radar_alerts(ticker: str) -> list:
        """
        Get current opportunity radar alerts for a specific ticker.
        Returns list of alerts: type, title, body, strength, direction, suggested_action, evidence.
        """
        ticker  = ticker.upper().replace(".NS", "")
        alerts  = radar.scan([ticker])
        return [a.to_dict() for a in alerts[:5]]

    # ──────────────────────────────────────────
    # SEARCH COMPANIES
    # ──────────────────────────────────────────

    def search_companies(query: str) -> list:
        """
        Search for companies in the knowledge graph by name or ticker.
        Returns list of {ticker, name, sector, graph_id}.
        """
        from graph.entities import EntityType
        results = repo.search_partial(query, limit=10)
        return [
            {
                "ticker":   n.ticker,
                "name":     n.canonical_name,
                "sector":   n.attributes.get("sector"),
                "graph_id": n.id,
            }
            for n in results
            if n.ontology_type == EntityType.COMPANY
        ]

    # ──────────────────────────────────────────
    # EXPLORE CONNECTIONS
    # ──────────────────────────────────────────

    def explore_connections(ticker_or_graph_id: str, depth: int = 1) -> list:
        """
        Explore graph connections for a company (competitors, sector, executives, events).
        depth=1 for direct connections, depth=2 for second-degree.
        Returns list of {relation, target_name, target_type, target_ticker}.
        """
        # Resolve to node_id
        ticker_clean = ticker_or_graph_id.upper().replace(".NS", "")
        node         = graph.get_company_node(ticker_clean)

        if not node:
            node = graph.get_node(ticker_or_graph_id)

        if not node:
            return [{"error": f"Cannot find {ticker_or_graph_id} in graph."}]

        if depth == 1:
            hops = graph.one_hop(node.id)
            return [
                {
                    "relation":     rel.relation_type,
                    "target_name":  tgt.canonical_name,
                    "target_type":  tgt.ontology_type,
                    "target_ticker": tgt.ticker,
                    "weight":       round(weight, 3),
                }
                for rel, tgt, weight in hops
            ][:20]
        else:
            multi = graph.multi_hop(node.id, depth=min(depth, 2))
            return [
                {
                    "source_id":    src_id,
                    "relation":     rel.relation_type,
                    "target_name":  (graph.get_node(tgt_id) or {}).canonical_name
                        if hasattr(graph.get_node(tgt_id), "canonical_name") else tgt_id,
                    "target_type":  graph.get_node(tgt_id).ontology_type if graph.get_node(tgt_id) else "?",
                    "weight":       round(weight, 3),
                }
                for src_id, rel, tgt_id, weight in multi
            ][:30]

    # ──────────────────────────────────────────
    # PORTFOLIO
    # ──────────────────────────────────────────

    def get_portfolio() -> dict:
        """
        Get the user's current watchlist and holdings.
        Returns: watchlist (list of tickers), holdings (dict of ticker→qty+avg_price).
        """
        return portfolio or {"watchlist": [], "holdings": {}}

    # ──────────────────────────────────────────
    # GRAPH SUMMARY
    # ──────────────────────────────────────────

    def graph_summary() -> dict:
        """
        Overview of what's in the Vrishabh knowledge graph.
        Returns counts of entity types, total nodes, total relations.
        """
        return repo.summary()

    # ──────────────────────────────────────────
    # MACRO INDICATORS
    # ──────────────────────────────────────────

    def get_macro_indicators() -> list:
        """
        Get current macro indicators tracked by Vrishabh (Nifty50, Bank Nifty, FII flows, USD/INR etc.)
        """
        from graph.entities import EntityType
        nodes = graph.get_by_type(EntityType.MACRO_INDICATOR)
        return [
            {
                "name":   n.canonical_name,
                "value":  n.attributes.get("value"),
                "unit":   n.attributes.get("unit"),
                "as_of":  n.attributes.get("as_of"),
            }
            for n in nodes
        ]

    # ──────────────────────────────────────────
    # INDIA INTELLIGENCE GRAPH TOOLS
    # ──────────────────────────────────────────

    def india_search(query: str, limit: int = 10) -> list:
        """
        Search the India intelligence graph by entity name or topic.
        Covers: Indian companies, conglomerates, sectors, indices, mutual funds,
        government policy, RBI/SEBI decisions, budget events, macro indicators,
        economic trends, startup funding, corporate events, business groups.
        Returns list of {id, name, type, domain, attributes}.
        """
        if not india_repo:
            return [{"error": "India graph not available."}]
        results = india_repo.search(query, limit=limit)
        return [
            {
                "id":         e.id,
                "name":       e.canonical_name,
                "type":       e.entity_type,
                "domain":     e.domain,
                "attributes": e.attributes,
            }
            for e in results
        ]

    def india_explore_neighbors(entity_id: str, hops: int = 1) -> dict:
        """
        Explore connections around an India graph entity.
        entity_id: node id from india_search().
        Returns subgraph with nodes and edges.
        Use to find: which sectors a company belongs to, what policies affect it,
        related conglomerate, competitor companies, etc.
        """
        if not india_repo:
            return {"error": "India graph not available."}
        return india_repo.entity_subgraph(entity_id, hops=min(hops, 2))

    def india_semantic_search(query: str, limit: int = 8) -> list:
        """
        Embedding-based semantic search of the India intelligence graph.
        Best for conceptual queries like 'companies affected by RBI rate hike'
        or 'Indian conglomerates with infrastructure exposure'.
        Returns list of {id, name, type, domain, attributes}.
        """
        if not india_repo:
            return [{"error": "India graph not available."}]
        results = india_repo.semantic_search(query, limit=limit)
        return [
            {
                "id":         e.id,
                "name":       e.canonical_name,
                "type":       e.entity_type,
                "domain":     e.domain,
                "attributes": e.attributes,
            }
            for e in results
        ]

    def india_graph_summary() -> dict:
        """
        Overview of the India intelligence graph (nodes, relations, domain breakdown).
        Domains: india_finance, india_policy, india_economy, india_corporate.
        """
        if not india_repo:
            return {"error": "India graph not available."}
        return india_repo.summary()

    # ──────────────────────────────────────────
    # GLOBAL GRAPH TOOLS
    # ──────────────────────────────────────────

    def global_search(query: str, limit: int = 10) -> list:
        """
        Search the global intelligence graph (corporate, geopolitics, climate, technology)
        by entity name, company, country, technology, or topic.
        Returns list of {id, name, type, domain, attributes}.
        """
        if not global_repo:
            return [{"error": "Global graph not available."}]
        results = global_repo.search(query, limit=limit)
        return [
            {
                "id":         e.id,
                "name":       e.canonical_name,
                "type":       e.entity_type,
                "domain":     e.domain,
                "attributes": e.attributes,
            }
            for e in results
        ]

    def global_explore_neighbors(entity_id: str, hops: int = 1) -> dict:
        """
        Explore connections around a global graph entity.
        entity_id: node id from global_search().
        Returns subgraph with nodes and edges.
        """
        if not global_repo:
            return {"error": "Global graph not available."}
        return global_repo.entity_subgraph(entity_id, hops=min(hops, 2))

    def global_semantic_search(query: str, limit: int = 8) -> list:
        """
        Semantic (embedding-based) search of the global graph.
        Best for conceptual queries like 'countries affected by semiconductor shortage'.
        Returns list of {id, name, type, domain, attributes}.
        """
        if not global_repo:
            return [{"error": "Global graph not available."}]
        results = global_repo.semantic_search(query, limit=limit)
        return [
            {
                "id":         e.id,
                "name":       e.canonical_name,
                "type":       e.entity_type,
                "domain":     e.domain,
                "attributes": e.attributes,
            }
            for e in results
        ]

    def global_graph_summary() -> dict:
        """
        Overview of the global intelligence graph (nodes, relations, domain breakdown).
        """
        if not global_repo:
            return {"error": "Global graph not available."}
        return global_repo.summary()

    # ──────────────────────────────────────────
    # WATCH CONDITIONS
    # ──────────────────────────────────────────

    def create_watch(
        ticker: str,
        metric: str,
        operator: str,
        threshold,
        description: str = "",
    ) -> dict:
        """
        Create an autonomous watch condition that Vrishabh monitors after every market sync.
        When the condition is met, a notification fires into the user's chat.

        ticker:      NSE ticker (e.g. "RELIANCE", "TCS")
        metric:      "price" | "pct_change" | "ta_score" | "action"
        operator:    ">" | "<" | ">=" | "<=" | "==" (use "==" with action)
        threshold:   numeric value, or string like "BUY"/"SELL" when metric=="action"
        description: human-readable label shown in the notification
                     (e.g. "RELIANCE breaks above ₹1450")
        Returns: {id, status, description}
        """
        import json as _json, os as _os, uuid as _uuid, datetime as _dt
        _watches_path = _os.path.join(_os.path.dirname(__file__), "..", "data", "watches.json")
        try:
            watches = _json.loads(open(_watches_path).read()) if _os.path.exists(_watches_path) else []
        except Exception:
            watches = []
        w = {
            "id":          str(_uuid.uuid4())[:8],
            "ticker":      ticker.upper().replace(".NS", ""),
            "metric":      metric,
            "operator":    operator,
            "threshold":   threshold,
            "description": description or f"{ticker} {metric} {operator} {threshold}",
            "created_at":  _dt.datetime.utcnow().isoformat(),
            "fired_at":    None,
            "active":      True,
        }
        watches.append(w)
        _os.makedirs(_os.path.dirname(_watches_path), exist_ok=True)
        with open(_watches_path, "w") as _f:
            _json.dump(watches, _f, indent=2)
        return {"id": w["id"], "status": "created", "description": w["description"]}

    # ──────────────────────────────────────────
    # PERSISTENT MEMORY
    # ──────────────────────────────────────────

    def remember(content: str) -> dict:
        """
        Save an important fact to persistent memory.
        This memory will be injected as context in ALL future conversations.
        Use sparingly — only for genuinely important, durable facts.

        Examples of good memories:
          "User is focused on mid-cap IT stocks"
          "User asked about HDFC Bank breakout on 2025-03-29, watching ₹1800 level"
          "User wants concise answers with specific price levels"

        content: the fact to remember (1-3 sentences)
        Returns: {status: "saved", id}
        """
        import json as _json, os as _os, uuid as _uuid, datetime as _dt
        _mem_path = _os.path.join(_os.path.dirname(__file__), "..", "data", "memory.json")
        try:
            memories = _json.loads(open(_mem_path, encoding="utf-8").read()) if _os.path.exists(_mem_path) else []
        except Exception:
            memories = []
        entry = {
            "id":         str(_uuid.uuid4())[:8],
            "content":    content,
            "created_at": _dt.datetime.utcnow().isoformat(),
        }
        memories.append(entry)
        _os.makedirs(_os.path.dirname(_mem_path), exist_ok=True)
        with open(_mem_path, "w", encoding="utf-8") as _f:
            _json.dump(memories[-50:], _f, ensure_ascii=False, indent=2)
        return {"status": "saved", "id": entry["id"]}

    # ──────────────────────────────────────────
    # TOOL EXPORT
    # ──────────────────────────────────────────

    return {
        "get_company_info": {
            "tool": get_company_info,
            "description": "Get metadata for a stock (name, sector, market cap) from the knowledge graph.",
        },
        "get_technical_signals": {
            "tool": get_technical_signals,
            "description": "Get TA signals: score, regime, action, confidence, patterns, support/resistance.",
        },
        "get_news_sentiment": {
            "tool": get_news_sentiment,
            "description": "Get business news sentiment score (-1 to +1) and headline summary for a stock.",
        },
        "get_insider_activity": {
            "tool": get_insider_activity,
            "description": "Get recent insider/bulk/block trades for a stock from the knowledge graph.",
        },
        "get_filings": {
            "tool": get_filings,
            "description": "Get recent corporate filings (quarterly results, BSE disclosures) for a stock.",
        },
        "get_radar_alerts": {
            "tool": get_radar_alerts,
            "description": "Get current Opportunity Radar alerts for a specific stock.",
        },
        "search_companies": {
            "tool": search_companies,
            "description": "Search for companies in the knowledge graph by name or partial ticker.",
        },
        "explore_connections": {
            "tool": explore_connections,
            "description": "Explore graph connections for a company: sector, executives, events, competitors.",
        },
        "get_portfolio": {
            "tool": get_portfolio,
            "description": "Get the user's current watchlist and stock holdings.",
        },
        "graph_summary": {
            "tool": graph_summary,
            "description": "Overview of the Vrishabh knowledge graph: entity counts and domains.",
        },
        "get_macro_indicators": {
            "tool": get_macro_indicators,
            "description": "Get current macro data: Nifty50, Bank Nifty, USD/INR, FII flows etc.",
        },
        "india_search": {
            "tool": india_search,
            "description": "Search India intelligence graph: companies, policy, RBI/SEBI, macro, startups, conglomerates.",
        },
        "india_explore_neighbors": {
            "tool": india_explore_neighbors,
            "description": "Explore graph connections around an India graph entity (by id from india_search).",
        },
        "india_semantic_search": {
            "tool": india_semantic_search,
            "description": "Semantic search of India graph for conceptual queries (e.g. 'companies affected by rate hike').",
        },
        "india_graph_summary": {
            "tool": india_graph_summary,
            "description": "Overview of the India intelligence graph: nodes, relations, domain breakdown.",
        },
        "global_search": {
            "tool": global_search,
            "description": "Search the global intelligence graph (corporate/geopolitics/climate/tech) by name or topic.",
        },
        "global_explore_neighbors": {
            "tool": global_explore_neighbors,
            "description": "Explore connections around a global graph entity (by id from global_search).",
        },
        "global_semantic_search": {
            "tool": global_semantic_search,
            "description": "Embedding-based semantic search of the global graph for conceptual queries.",
        },
        "global_graph_summary": {
            "tool": global_graph_summary,
            "description": "Overview of the global intelligence graph: nodes, relations, domain breakdown.",
        },
        "create_watch": {
            "tool": create_watch,
            "description": (
                "Create an autonomous watch condition monitored after every market sync. "
                "Use when the user says 'alert me when X' or 'notify me if Y'. "
                "metric: price|pct_change|ta_score|action. "
                "operator: >|<|>=|<=|== (== for action match e.g. 'BUY'). "
                "A notification fires into the chat automatically when the condition is met."
            ),
        },
        "remember": {
            "tool": remember,
            "description": (
                "Save an important fact to persistent memory — injected as context in ALL future chats. "
                "Use for durable user preferences, key price levels being watched, or notable insights. "
                "Do NOT use for transient facts that are already in the knowledge graph."
            ),
        },
    }
