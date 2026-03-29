"""
India Economy domain ontology.
Entity types: MacroIndicator, EconomicTrend, ForeignInvestment, TradeData, InfrastructureProject
"""

DOMAIN = "india_economy"

ECONOMY_SCHEMA = {
    "MacroIndicator": {
        "required": ["name"],
        "optional": ["value", "unit", "date", "source", "trend",
                     "yoy_change_pct", "mom_change_pct", "description"],
    },
    "EconomicTrend": {
        "required": ["name"],
        "optional": ["category", "magnitude", "outlook", "drivers",
                     "affected_sectors", "timeframe", "description"],
    },
    "ForeignInvestment": {
        "required": ["name"],
        "optional": ["flow_type", "amount_usd_bn", "quarter", "source_country",
                     "sector", "route", "description"],
    },
    "TradeData": {
        "required": ["name"],
        "optional": ["trade_type", "value_usd_bn", "partner_country",
                     "commodity", "period", "yoy_change_pct", "description"],
    },
    "InfrastructureProject": {
        "required": ["name"],
        "optional": ["project_type", "cost_cr", "location", "status",
                     "completion_date", "developer", "description"],
    },
}

ECONOMY_RELATIONS = [
    "DRIVES",
    "IMPACTS",
    "CORRELATES_WITH",
    "MEASURES",
    "FLOWS_INTO",
    "FLOWS_FROM",
    "AFFECTS_SECTOR",
    "FUNDED_BY",
    "EXECUTED_BY",
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
                    "entity_type": {"type": "string", "enum": list(ECONOMY_SCHEMA.keys())},
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
                    "relation_type": {"type": "string", "enum": ECONOMY_RELATIONS},
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

ARBITER_SYSTEM_PROMPT = f"""You are an Indian macroeconomic intelligence extraction engine.
Extract all Indian economic entities and trends from the provided text.

Valid entity types: {list(ECONOMY_SCHEMA.keys())}
Valid relation types: {ECONOMY_RELATIONS}

Rules:
- Focus on India's GDP, inflation (CPI/WPI), IIP, PMI, current account, fiscal deficit,
  FDI/FPI flows, trade data, infrastructure projects, and economic trends.
- canonical_name must be precise and official
- weight: 0.0 (speculative) to 1.0 (definitive)
- confidence: 0.0 to 1.0
"""
