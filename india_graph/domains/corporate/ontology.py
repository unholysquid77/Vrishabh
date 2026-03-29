"""
India Corporate domain ontology.
Entity types: Promoter, CorporateEvent, StartupFunding, Analyst, BusinessGroup
"""

DOMAIN = "india_corporate"

INDIA_CORPORATE_SCHEMA = {
    "Promoter": {
        "required": ["name"],
        "optional": ["company", "holding_pct", "role", "family_group", "description"],
    },
    "CorporateEvent": {
        "required": ["name"],
        "optional": ["event_type", "company", "date", "amount_cr",
                     "quarter", "yoy_change_pct", "status", "impact", "description"],
    },
    "StartupFunding": {
        "required": ["name"],
        "optional": ["startup", "round", "amount_usd_mn", "investors",
                     "date", "valuation_usd_mn", "sector", "description"],
    },
    "Analyst": {
        "required": ["name"],
        "optional": ["firm", "coverage_sectors", "rating", "target_price", "description"],
    },
    "BusinessGroup": {
        "required": ["name"],
        "optional": ["patriarch", "key_companies", "revenue_cr", "sectors",
                     "listed_entities", "description"],
    },
}

INDIA_CORPORATE_RELATIONS = [
    "PROMOTED_BY",
    "FUNDED_BY",
    "ACQUIRED_BY",
    "PARTNERED_WITH",
    "REPORTED_EARNINGS",
    "COVERED_BY_ANALYST",
    "RATED_BY",
    "COMPETES_WITH",
    "BELONGS_TO_GROUP",
    "SPUN_OFF_FROM",
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
                    "entity_type": {"type": "string", "enum": list(INDIA_CORPORATE_SCHEMA.keys())},
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
                    "relation_type": {"type": "string", "enum": INDIA_CORPORATE_RELATIONS},
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

ARBITER_SYSTEM_PROMPT = f"""You are an Indian corporate intelligence extraction engine.
Extract Indian corporate entities and relationships from the provided text.

Valid entity types: {list(INDIA_CORPORATE_SCHEMA.keys())}
Valid relation types: {INDIA_CORPORATE_RELATIONS}

Rules:
- Focus on Indian promoters/founders, quarterly earnings events, startup funding rounds,
  analyst coverage, and Indian business groups (Tata Group, Adani Group, Birla Group, etc.)
- canonical_name must be the official name
- For CorporateEvent, event_type should be one of: earnings, fundraise, acquisition, divestment,
  expansion, restructuring, regulatory_action, management_change
- weight: 0.0 (speculative) to 1.0 (definitive)
- confidence: 0.0 to 1.0
"""
