"""
Geopolitics domain ontology.
Entity types: Country, PoliticalLeader, Alliance, Conflict, Treaty, SanctionEvent
"""

DOMAIN = "geopolitics"

GEOPOLITICS_SCHEMA = {
    "Country": {
        "required": ["name"],
        "optional": ["iso_code", "region", "government_type", "gdp_usd",
                     "population", "capital", "description"],
    },
    "PoliticalLeader": {
        "required": ["name"],
        "optional": ["title", "country", "party", "since", "age"],
    },
    "Alliance": {
        "required": ["name"],
        "optional": ["type", "members", "founded", "purpose", "description"],
    },
    "Conflict": {
        "required": ["name"],
        "optional": ["type", "start_date", "end_date", "parties",
                     "region", "casualties", "status", "description"],
    },
    "Treaty": {
        "required": ["name"],
        "optional": ["type", "signatories", "date", "status", "description"],
    },
    "SanctionEvent": {
        "required": ["name"],
        "optional": ["imposer", "target", "date", "reason", "scope", "description"],
    },
}

GEOPOLITICS_RELATIONS = [
    "ALLY_OF",
    "RIVAL_OF",
    "SANCTIONS",
    "INVADED",
    "SIGNED_TREATY_WITH",
    "MEMBER_OF",
    "LED_BY",
    "TRADES_WITH",
    "HOSTS_BASE_IN",
    "CONFLICT_WITH",
    "BORDERS",
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
                    "entity_type": {"type": "string", "enum": list(GEOPOLITICS_SCHEMA.keys())},
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
                    "relation_type": {"type": "string", "enum": GEOPOLITICS_RELATIONS},
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

ARBITER_SYSTEM_PROMPT = f"""You are a geopolitical intelligence extraction engine.
Extract all geopolitical entities and relations from the provided text.

Valid entity types: {list(GEOPOLITICS_SCHEMA.keys())}
Valid relation types: {GEOPOLITICS_RELATIONS}

Rules:
- canonical_name must be the most official English name
- Use ISO country names where applicable
- weight for relations: 0.0 (weak) to 1.0 (definitive)
- confidence for entities: 0.0 to 1.0
"""
