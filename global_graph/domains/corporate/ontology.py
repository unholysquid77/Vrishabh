"""
Corporate domain ontology.
Entity types: Organization, Person, Product, Market, DealEvent, Regulation
"""

DOMAIN = "corporate"

CORPORATE_SCHEMA = {
    "Organization": {
        "required": ["name"],
        "optional": ["sector", "country", "founded", "revenue", "employees",
                     "stock_ticker", "description", "hq_city"],
    },
    "Person": {
        "required": ["name"],
        "optional": ["title", "organization", "nationality", "age"],
    },
    "Product": {
        "required": ["name"],
        "optional": ["category", "maker", "launch_year", "description"],
    },
    "Market": {
        "required": ["name"],
        "optional": ["size_usd", "growth_rate", "geography", "sector"],
    },
    "DealEvent": {
        "required": ["name"],
        "optional": ["deal_type", "acquirer", "target", "value_usd", "date",
                     "status", "description"],
    },
    "Regulation": {
        "required": ["name"],
        "optional": ["jurisdiction", "authority", "date", "impact", "description"],
    },
}

CORPORATE_RELATIONS = [
    "HEADQUARTERED_IN",
    "CEO_OF",
    "BOARD_MEMBER_OF",
    "COMPETES_WITH",
    "ACQUIRED",
    "PARTNERED_WITH",
    "SUPPLIES_TO",
    "INVESTED_IN",
    "REGULATED_BY",
    "OPERATES_IN",
    "LAUNCHED",
    "MERGED_WITH",
    "LLM_AFFINITY",
]

# JSON schema for LLM arbiter output
ARBITER_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entity_type": {"type": "string", "enum": list(CORPORATE_SCHEMA.keys())},
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
                    "relation_type": {"type": "string", "enum": CORPORATE_RELATIONS},
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

ARBITER_SYSTEM_PROMPT = f"""You are a corporate intelligence extraction engine.
Extract all entities and relations from the provided text.

Valid entity types: {list(CORPORATE_SCHEMA.keys())}
Valid relation types: {CORPORATE_RELATIONS}

Rules:
- canonical_name must be the most formal / official name
- Provide aliases for abbreviations, common names, stock tickers
- attributes must only use the allowed keys for that entity type
- weight for relations: 0.0 (weak/speculative) to 1.0 (definitive)
- confidence for entities: 0.0 to 1.0 based on how explicitly mentioned
"""
