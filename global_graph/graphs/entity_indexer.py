"""
EntityIndexer — builds and maintains a reverse name→node_id index
for fast fuzzy entity lookup.
"""

from __future__ import annotations
import re
from typing import Dict, List, Optional, Set

from global_graph.core.base_entity import BaseEntity
from global_graph.graphs.ontology_graph import OntologyGraph


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse spaces."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class EntityIndexer:
    """
    Maintains a normalized name → List[node_id] index.
    Rebuilt on demand; incremental updates on ingestion.
    """

    def __init__(self, graph: OntologyGraph):
        self._graph   = graph
        self._index:  Dict[str, List[str]] = {}   # normalized_name → [node_id]

    def rebuild(self):
        """Full rebuild from current graph state."""
        self._index.clear()
        for entity in self._graph.nodes.values():
            self._index_entity(entity)

    def index_entity(self, entity: BaseEntity):
        """Incrementally index a single entity."""
        self._index_entity(entity)

    def _index_entity(self, entity: BaseEntity):
        for name in entity.all_names():
            key = _normalize(name)
            if key:
                if key not in self._index:
                    self._index[key] = []
                if entity.id not in self._index[key]:
                    self._index[key].append(entity.id)

    def remove_entity(self, entity: BaseEntity):
        """Remove an entity from the index."""
        for name in entity.all_names():
            key = _normalize(name)
            if key in self._index:
                self._index[key] = [i for i in self._index[key] if i != entity.id]
                if not self._index[key]:
                    del self._index[key]

    def lookup(self, name: str) -> List[str]:
        """Exact normalized lookup. Returns list of node_ids."""
        return self._index.get(_normalize(name), [])

    def all_keys(self) -> List[str]:
        return list(self._index.keys())

    def stats(self) -> Dict:
        return {
            "index_keys": len(self._index),
            "total_entries": sum(len(v) for v in self._index.values()),
        }
