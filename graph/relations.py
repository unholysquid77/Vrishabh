from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from .entities import SourceInfo


# ──────────────────────────────────────────────
# RELATION TYPE CONSTANTS
# ──────────────────────────────────────────────

class RelationType:
    # Company structural
    IN_SECTOR       = "IN_SECTOR"        # Company → Sector
    MANAGED_BY      = "MANAGED_BY"       # Company → Executive
    COMPETES_WITH   = "COMPETES_WITH"    # Company ↔ Company

    # Corporate actions
    FILED           = "FILED"            # Company → Filing
    HAD_EVENT       = "HAD_EVENT"        # Company → Event
    ACQUIRED        = "ACQUIRED"         # Company → Company
    SPUN_OFF        = "SPUN_OFF"         # Company → Company

    # Market activity
    INSIDER_TRADED  = "INSIDER_TRADED"   # Company → InsiderTrade
    MENTIONED_IN    = "MENTIONED_IN"     # Company → NewsItem

    # Macro linkage
    AFFECTED_BY     = "AFFECTED_BY"      # Company → MacroIndicator
    TRACKS          = "TRACKS"           # Sector → MacroIndicator

    # LLM-inferred semantic affinity
    LLM_AFFINITY    = "LLM_AFFINITY"     # any → any


# ──────────────────────────────────────────────
# CANONICAL RELATION MODEL
# ──────────────────────────────────────────────

class FinanceRelation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))

    relation_type: str              # RelationType constant
    from_node_id: str
    to_node_id: str

    weight: float                   = 1.0
    attributes: Dict[str, Any]      = Field(default_factory=dict)

    sources: List[SourceInfo]       = Field(default_factory=list)
    created_at: datetime            = Field(default_factory=datetime.utcnow)
    confidence: float               = 1.0


# ──────────────────────────────────────────────
# FACTORY
# ──────────────────────────────────────────────

def make_relation(
    relation_type: str,
    from_node_id: str,
    to_node_id: str,
    weight: float                   = 1.0,
    attributes: Optional[Dict[str, Any]] = None,
    sources: Optional[List[SourceInfo]]  = None,
    confidence: float               = 1.0,
) -> FinanceRelation:
    return FinanceRelation(
        relation_type=relation_type,
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        weight=weight,
        attributes=attributes or {},
        sources=sources or [],
        confidence=confidence,
    )
