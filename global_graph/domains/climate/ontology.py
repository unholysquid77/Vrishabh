"""
Climate domain ontology.
Entity types: ClimateEvent, Country, Organization, Policy, NaturalResource, ClimateIndicator
"""

DOMAIN = "climate"

CLIMATE_SCHEMA = {
    "ClimateEvent": {
        "required": ["name"],
        "optional": ["event_type", "region", "date", "severity", "casualties",
                     "economic_loss_usd", "description"],
    },
    "ClimatePolicy": {
        "required": ["name"],
        "optional": ["jurisdiction", "authority", "date", "target",
                     "status", "description"],
    },
    "NaturalResource": {
        "required": ["name"],
        "optional": ["resource_type", "region", "reserve_size", "description"],
    },
    "ClimateIndicator": {
        "required": ["name"],
        "optional": ["value", "unit", "date", "source", "trend", "description"],
    },
    "ClimateOrganization": {
        "required": ["name"],
        "optional": ["type", "country", "focus", "description"],
    },
}

CLIMATE_RELATIONS = [
    "CAUSED_BY",
    "IMPACTS",
    "REGULATES",
    "SIGNED_AGREEMENT",
    "EMITS",
    "DEPENDS_ON",
    "THREATENED_BY",
    "MONITORS",
    "FUNDS",
    "LOCATED_IN",
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
                    "entity_type": {"type": "string", "enum": list(CLIMATE_SCHEMA.keys())},
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
                    "relation_type": {"type": "string", "enum": CLIMATE_RELATIONS},
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

ARBITER_SYSTEM_PROMPT = f"""You are a climate and environmental intelligence extraction engine.
Extract all climate-related entities and relations from the provided text.

Valid entity types: {list(CLIMATE_SCHEMA.keys())}
Valid relation types: {CLIMATE_RELATIONS}

Rules:
- Focus on climate events, policies, natural resources, indicators, and organizations
- canonical_name must be precise and official
- weight: 0.0 (speculative) to 1.0 (definitive)
- confidence: 0.0 to 1.0
"""
