"""
Metadata models for global graph entities and relations.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class EntityMetadata:
    created_at:    str           = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at:    str           = field(default_factory=lambda: datetime.utcnow().isoformat())
    source_urls:   List[str]     = field(default_factory=list)
    raw_text:      Optional[str] = None
    ingestion_run: Optional[str] = None   # ISO timestamp of the run that created this

    def touch(self):
        self.updated_at = datetime.utcnow().isoformat()


@dataclass
class RelationMetadata:
    created_at:    str           = field(default_factory=lambda: datetime.utcnow().isoformat())
    source_urls:   List[str]     = field(default_factory=list)
    ingestion_run: Optional[str] = None
