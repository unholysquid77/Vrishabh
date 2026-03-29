"""
EntityResolver — 4-tier fuzzy matching for entity deduplication.
Tiers: exact → canonical key → substring → Jaccard ≥ FUZZY_THRESHOLD.
"""

from __future__ import annotations
import re
from typing import List, Optional

from global_graph.core.base_entity import BaseEntity
from global_graph.graphs.entity_indexer import EntityIndexer
from global_graph.graphs.ontology_graph import OntologyGraph

FUZZY_THRESHOLD = 0.75


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _canonical_key(text: str) -> str:
    """Strip common suffixes like Inc, Ltd, Corp, etc."""
    suffixes = [
        r"\b(inc|ltd|llc|corp|corporation|limited|plc|gmbh|sa|nv|ag|co)\b\.?$"
    ]
    text = _normalize(text)
    for pat in suffixes:
        text = re.sub(pat, "", text).strip()
    return text


def _tokenize(text: str):
    return set(_normalize(text).split())


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class EntityResolver:

    def __init__(self, graph: OntologyGraph, indexer: EntityIndexer):
        self._graph   = graph
        self._indexer = indexer

    def resolve(
        self,
        name:        str,
        entity_type: Optional[str] = None,
    ) -> Optional[BaseEntity]:
        """
        Find the best existing entity matching `name`.
        Optionally restricted to `entity_type`.
        Returns None if no confident match found.
        """
        # Tier 1: exact normalized match
        candidates = self._indexer.lookup(name)
        for cid in candidates:
            e = self._graph.nodes.get(cid)
            if e and (entity_type is None or e.entity_type == entity_type):
                return e

        # Tier 2: canonical key match (strip suffixes)
        key = _canonical_key(name)
        for e in self._iter_typed(entity_type):
            if _canonical_key(e.canonical_name) == key:
                return e

        # Tier 3: substring containment
        nl = _normalize(name)
        for e in self._iter_typed(entity_type):
            for n in e.all_names():
                nn = _normalize(n)
                if nl in nn or nn in nl:
                    return e

        # Tier 4: Jaccard ≥ FUZZY_THRESHOLD
        best_score = 0.0
        best_entity: Optional[BaseEntity] = None
        for e in self._iter_typed(entity_type):
            for n in e.all_names():
                score = _jaccard(name, n)
                if score >= FUZZY_THRESHOLD and score > best_score:
                    best_score  = score
                    best_entity = e

        return best_entity

    def _iter_typed(self, entity_type: Optional[str]):
        if entity_type:
            for eid in self._graph.type_index.get(entity_type, []):
                e = self._graph.nodes.get(eid)
                if e:
                    yield e
        else:
            yield from self._graph.nodes.values()
