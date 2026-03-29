"""
Technology domain ontology.
Entity types: TechCompany, Technology, ResearchPaper, Patent, TechEvent, Regulation
"""

DOMAIN = "technology"

TECHNOLOGY_SCHEMA = {
    "TechCompany": {
        "required": ["name"],
        "optional": ["sector", "country", "founded", "valuation_usd",
                     "employees", "stock_ticker", "hq_city", "description"],
    },
    "Technology": {
        "required": ["name"],
        "optional": ["category", "maturity", "creator", "year_introduced",
                     "use_cases", "description"],
    },
    "ResearchPaper": {
        "required": ["name"],
        "optional": ["authors", "institution", "venue", "year",
                     "abstract_summary", "doi"],
    },
    "Patent": {
        "required": ["name"],
        "optional": ["assignee", "inventor", "year", "jurisdiction",
                     "status", "description"],
    },
    "TechEvent": {
        "required": ["name"],
        "optional": ["event_type", "date", "participants", "outcome", "description"],
    },
    "TechRegulation": {
        "required": ["name"],
        "optional": ["jurisdiction", "authority", "date", "scope", "description"],
    },
}

TECHNOLOGY_RELATIONS = [
    "DEVELOPED_BY",
    "ACQUIRED_BY",
    "COMPETES_WITH",
    "PARTNERED_WITH",
    "INVESTED_IN",
    "USES",
    "REGULATES",
    "PUBLISHED_BY",
    "CITED_BY",
    "PATENTED_BY",
    "SUCCESSOR_OF",
    "POWERS",
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
                    "entity_type": {"type": "string", "enum": list(TECHNOLOGY_SCHEMA.keys())},
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
                    "relation_type": {"type": "string", "enum": TECHNOLOGY_RELATIONS},
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

ARBITER_SYSTEM_PROMPT = f"""You are a technology intelligence extraction engine.
Extract all technology-related entities and relations from the provided text.

Valid entity types: {list(TECHNOLOGY_SCHEMA.keys())}
Valid relation types: {TECHNOLOGY_RELATIONS}

Rules:
- Focus on tech companies, technologies, research, patents, events, and regulations
- canonical_name must be the official name
- weight: 0.0 (speculative) to 1.0 (definitive)
- confidence: 0.0 to 1.0
"""
