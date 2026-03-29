"""
SchemaRegistry — central ontology enforcement for the global graph.
Validates entity types, required attributes, and allowed relation types.
Silently strips unknown LLM-hallucinated attributes.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Set


class SchemaRegistry:
    """
    Holds the union ontology from all registered domain ontologies.
    Each domain registers its entity_types, relation_types, and attribute schemas.
    """

    def __init__(self):
        # entity_type → {required: [...], optional: [...], domain: str}
        self._entity_schemas:   Dict[str, Dict] = {}
        # Set of valid relation_type strings
        self._relation_types:   Set[str]         = set()
        # domain → [entity_types]
        self._domain_map:       Dict[str, List[str]] = {}

    # ── Registration ──────────────────────────────────────────────────────

    def register_domain(
        self,
        domain:         str,
        entity_schemas: Dict[str, Dict],   # {entity_type: {required, optional}}
        relation_types: List[str],
    ):
        """Register a domain's ontology. Safe to call multiple times (merges)."""
        self._domain_map[domain] = list(entity_schemas.keys())
        for etype, schema in entity_schemas.items():
            self._entity_schemas[etype] = {**schema, "domain": domain}
        self._relation_types.update(relation_types)

    # ── Validation ────────────────────────────────────────────────────────

    def valid_entity_type(self, entity_type: str) -> bool:
        return entity_type in self._entity_schemas

    def valid_relation_type(self, relation_type: str) -> bool:
        return relation_type in self._relation_types

    def get_domain_for_type(self, entity_type: str) -> Optional[str]:
        schema = self._entity_schemas.get(entity_type)
        return schema["domain"] if schema else None

    def sanitize_attributes(self, entity_type: str, attributes: Dict[str, Any]) -> Dict[str, Any]:
        """
        Keep only known attributes (required + optional) for the entity type.
        Unknown keys are silently dropped.
        """
        schema = self._entity_schemas.get(entity_type)
        if not schema:
            return attributes
        allowed: Set[str] = set(schema.get("required", [])) | set(schema.get("optional", []))
        return {k: v for k, v in attributes.items() if k in allowed}

    def required_attributes(self, entity_type: str) -> List[str]:
        schema = self._entity_schemas.get(entity_type, {})
        return schema.get("required", [])

    # ── Introspection ─────────────────────────────────────────────────────

    def all_entity_types(self) -> List[str]:
        return list(self._entity_schemas.keys())

    def all_relation_types(self) -> List[str]:
        return sorted(self._relation_types)

    def domain_entity_types(self, domain: str) -> List[str]:
        return self._domain_map.get(domain, [])

    def summary(self) -> Dict[str, Any]:
        return {
            "domains":        list(self._domain_map.keys()),
            "entity_types":   len(self._entity_schemas),
            "relation_types": len(self._relation_types),
        }
