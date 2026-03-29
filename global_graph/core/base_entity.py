"""
BaseEntity — universal node for the global ontology graph.
"""

from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from global_graph.core.metadata import EntityMetadata


@dataclass
class BaseEntity:
    # ── identity ──────────────────────────────────────────────────────────
    id:             str             = field(default_factory=lambda: str(uuid.uuid4()))
    entity_type:    str             = ""            # e.g. "Organization", "Person", "Country"
    domain:         str             = ""            # "corporate" | "geopolitics" | "climate" | "technology"
    canonical_name: str             = ""
    aliases:        List[str]       = field(default_factory=list)

    # ── ontology attributes ───────────────────────────────────────────────
    attributes:     Dict[str, Any]  = field(default_factory=dict)

    # ── provenance ────────────────────────────────────────────────────────
    sources:        List[str]       = field(default_factory=list)   # article URLs / doc IDs
    confidence:     float           = 1.0

    # ── metadata ──────────────────────────────────────────────────────────
    metadata:       EntityMetadata  = field(default_factory=EntityMetadata)

    # ── helpers ───────────────────────────────────────────────────────────
    def all_names(self) -> List[str]:
        """All searchable name variants."""
        names = [self.canonical_name] + self.aliases
        return [n for n in names if n]

    def summary(self) -> str:
        attrs_str = ", ".join(f"{k}={v}" for k, v in list(self.attributes.items())[:4])
        return f"[{self.domain}/{self.entity_type}] {self.canonical_name} ({attrs_str})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":             self.id,
            "entity_type":    self.entity_type,
            "domain":         self.domain,
            "canonical_name": self.canonical_name,
            "aliases":        self.aliases,
            "attributes":     self.attributes,
            "sources":        self.sources,
            "confidence":     self.confidence,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BaseEntity":
        return cls(
            id             = d.get("id", str(uuid.uuid4())),
            entity_type    = d.get("entity_type", ""),
            domain         = d.get("domain", ""),
            canonical_name = d.get("canonical_name", ""),
            aliases        = d.get("aliases", []),
            attributes     = d.get("attributes", {}),
            sources        = d.get("sources", []),
            confidence     = d.get("confidence", 1.0),
        )
