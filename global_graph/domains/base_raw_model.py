"""
BaseRawModel — quarantine container for raw ingested text before LLM extraction.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class BaseRawModel:
    text:        str
    source_url:  str
    domain:      str             = ""
    title:       Optional[str]   = None
    published:   Optional[str]   = None   # ISO datetime string
    tags:        List[str]       = field(default_factory=list)
    ingested_at: str             = field(default_factory=lambda: datetime.utcnow().isoformat())
