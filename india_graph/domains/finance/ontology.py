"""
India Finance domain ontology.
Entity types: IndianCompany, Conglomerate, Sector, StockIndex, MutualFund, ETF
"""

DOMAIN = "india_finance"

FINANCE_SCHEMA = {
    "IndianCompany": {
        "required": ["name"],
        "optional": ["nse_ticker", "bse_ticker", "sector", "industry", "market_cap_cr",
                     "exchange", "promoter_holding_pct", "fii_holding_pct", "dii_holding_pct",
                     "incorporated", "hq_city", "description"],
    },
    "Conglomerate": {
        "required": ["name"],
        "optional": ["founder", "key_companies", "sectors", "revenue_cr",
                     "employees", "hq_city", "description"],
    },
    "Sector": {
        "required": ["name"],
        "optional": ["nifty_sector", "pe_ratio", "market_cap_cr", "ytd_return_pct",
                     "top_stocks", "description"],
    },
    "StockIndex": {
        "required": ["name"],
        "optional": ["exchange", "base_value", "current_value", "ytd_return_pct",
                     "constituents_count", "description"],
    },
    "MutualFund": {
        "required": ["name"],
        "optional": ["fund_house", "category", "aum_cr", "nav", "returns_1y_pct",
                     "fund_manager", "description"],
    },
    "ETF": {
        "required": ["name"],
        "optional": ["fund_house", "underlying_index", "aum_cr", "expense_ratio", "description"],
    },
}

FINANCE_RELATIONS = [
    "LISTED_ON",
    "PART_OF_CONGLOMERATE",
    "IN_SECTOR",
    "TRACKS_INDEX",
    "COMPETES_WITH",
    "ACQUIRED",
    "INVESTED_IN",
    "SUBSIDIARY_OF",
    "PROMOTED_BY",
    "CONSTITUENT_OF",
    "LLM_AFFINITY",
]

ARBITER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string", "enum": list(FINANCE_SCHEMA.keys())},
                    "canonical_name": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "attributes": {"type": "object"},
                    "confidence": {"type": "number"},
                },
                "required": ["entity_type", "canonical_name"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "relation_type": {"type": "string", "enum": FINANCE_RELATIONS},
                    "from_entity":   {"type": "string"},
                    "to_entity":     {"type": "string"},
                    "weight":        {"type": "number"},
                    "attributes":    {"type": "object"},
                },
                "required": ["relation_type", "from_entity", "to_entity"],
            },
        },
    },
    "required": ["entities", "relations"],
}

ARBITER_SYSTEM_PROMPT = f"""You are an Indian financial markets intelligence extraction engine.
Extract all Indian finance and market entities from the provided text.

Valid entity types: {list(FINANCE_SCHEMA.keys())}
Valid relation types: {FINANCE_RELATIONS}

Rules:
- Focus on Indian listed companies (NSE/BSE), conglomerates (Tata, Reliance, Adani, etc.),
  market indices (NIFTY, SENSEX), sectors, mutual funds, and ETFs.
- canonical_name must be the most formal/official name
- Provide NSE/BSE ticker as alias where known
- weight: 0.0 (speculative) to 1.0 (definitive)
- confidence: 0.0 to 1.0
"""
