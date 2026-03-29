"""
BaseRelation — universal directed edge for the global ontology graph.
"""

from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List

from global_graph.core.metadata import RelationMetadata


@dataclass
class BaseRelation:
    id:            str              = field(default_factory=lambda: str(uuid.uuid4()))
    relation_type: str              = ""       # e.g. "HEADQUARTERED_IN", "LLM_AFFINITY"
    from_id:       str              = ""
    to_id:         str              = ""
    weight:        float            = 1.0
    attributes:    Dict[str, Any]   = field(default_factory=dict)
    sources:       List[str]        = field(default_factory=list)
    confidence:    float            = 1.0
    metadata:      RelationMetadata = field(default_factory=RelationMetadata)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id":            self.id,
            "relation_type": self.relation_type,
            "from_id":       self.from_id,
            "to_id":         self.to_id,
            "weight":        self.weight,
            "attributes":    self.attributes,
            "sources":       self.sources,
            "confidence":    self.confidence,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BaseRelation":
        return cls(
            id            = d.get("id", str(uuid.uuid4())),
            relation_type = d.get("relation_type", ""),
            from_id       = d.get("from_id", ""),
            to_id         = d.get("to_id", ""),
            weight        = d.get("weight", 1.0),
            attributes    = d.get("attributes", {}),
            sources       = d.get("sources", []),
            confidence    = d.get("confidence", 1.0),
        )
