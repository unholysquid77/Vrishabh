"""
India Policy domain ontology.
Entity types: GovernmentPolicy, RBIDecision, SEBIRegulation, BudgetEvent, GovernmentScheme
"""

DOMAIN = "india_policy"

POLICY_SCHEMA = {
    "GovernmentPolicy": {
        "required": ["name"],
        "optional": ["ministry", "date", "objective", "beneficiaries",
                     "budget_cr", "status", "sector_impact", "description"],
    },
    "RBIDecision": {
        "required": ["name"],
        "optional": ["decision_type", "repo_rate", "reverse_repo_rate", "crr", "slr",
                     "date", "mpc_vote", "rationale", "impact", "description"],
    },
    "SEBIRegulation": {
        "required": ["name"],
        "optional": ["circular_no", "date", "scope", "effective_date",
                     "impact", "category", "description"],
    },
    "BudgetEvent": {
        "required": ["name"],
        "optional": ["fiscal_year", "announcement_type", "amount_cr",
                     "sector_impact", "tax_change", "description"],
    },
    "GovernmentScheme": {
        "required": ["name"],
        "optional": ["ministry", "launch_date", "target_beneficiaries",
                     "outlay_cr", "status", "description"],
    },
    "Regulator": {
        "required": ["name"],
        "optional": ["type", "jurisdiction", "head", "established", "description"],
    },
}

POLICY_RELATIONS = [
    "REGULATED_BY_SEBI",
    "REGULATED_BY_RBI",
    "IMPACTED_BY_POLICY",
    "ANNOUNCED_IN_BUDGET",
    "BENEFITS_FROM_SCHEME",
    "ISSUED_BY",
    "TARGETS_SECTOR",
    "SUPERSEDES",
    "AMENDED_BY",
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
                    "entity_type": {"type": "string", "enum": list(POLICY_SCHEMA.keys())},
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
                    "relation_type": {"type": "string", "enum": POLICY_RELATIONS},
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

ARBITER_SYSTEM_PROMPT = f"""You are an Indian government and regulatory policy intelligence extraction engine.
Extract all Indian policy, regulatory, and budgetary entities from the provided text.

Valid entity types: {list(POLICY_SCHEMA.keys())}
Valid relation types: {POLICY_RELATIONS}

Rules:
- Focus on RBI monetary policy, SEBI regulations, Union Budget, government schemes (PLI, PM-KISAN etc.),
  ministry policies, and key regulators (RBI, SEBI, IRDAI, PFRDA, etc.)
- canonical_name must be the official name
- weight: 0.0 (speculative) to 1.0 (definitive)
- confidence: 0.0 to 1.0
"""
