"""
GraphDedup — post-ingestion deduplication pass.
Merges nodes whose canonical_name Jaccard similarity ≥ 0.90
(same entity_type required). Survivor: higher confidence + more edges.
"""

from __future__ import annotations
import re
from typing import Dict, List, Optional, Set, Tuple

from global_graph.core.base_entity import BaseEntity
from global_graph.graphs.ontology_graph import OntologyGraph
from global_graph.graphs.entity_indexer import EntityIndexer


def _tokenize(text: str) -> Set[str]:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return set(text.split())


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    intersection = ta & tb
    union        = ta | tb
    return len(intersection) / len(union)


class GraphDedup:
    THRESHOLD = 0.90

    def __init__(self, graph: OntologyGraph, indexer: EntityIndexer):
        self._graph   = graph
        self._indexer = indexer

    def run(self) -> int:
        """
        Find and merge duplicate nodes.
        Returns the number of merges performed.
        """
        merges = 0
        # Group by entity_type to reduce comparisons
        for entity_type, ids in list(self._graph.type_index.items()):
            entities = [self._graph.nodes[i] for i in ids if i in self._graph.nodes]
            merged: Set[str] = set()

            for i in range(len(entities)):
                if entities[i].id in merged:
                    continue
                for j in range(i + 1, len(entities)):
                    if entities[j].id in merged:
                        continue
                    if _jaccard(entities[i].canonical_name, entities[j].canonical_name) >= self.THRESHOLD:
                        survivor, loser = self._pick_survivor(entities[i], entities[j])
                        self._merge(survivor, loser)
                        merged.add(loser.id)
                        merges += 1

        return merges

    def _pick_survivor(self, a: BaseEntity, b: BaseEntity) -> Tuple[BaseEntity, BaseEntity]:
        """Higher confidence wins. Tie-break: more edges."""
        def score(e: BaseEntity) -> float:
            edge_count = len(self._graph.outgoing.get(e.id, [])) + \
                         len(self._graph.incoming.get(e.id, []))
            return e.confidence + 0.001 * edge_count

        if score(a) >= score(b):
            return a, b
        return b, a

    def _merge(self, survivor: BaseEntity, loser: BaseEntity):
        """
        Merge loser into survivor:
        - Redirect all loser's edges to survivor.
        - Merge aliases and sources.
        - Remove loser from graph and index.
        """
        # Redirect outgoing edges of loser
        for rel_id in list(self._graph.outgoing.get(loser.id, [])):
            rel = self._graph.relations.get(rel_id)
            if rel:
                rel.from_id = survivor.id
                self._graph.outgoing[survivor.id].append(rel_id)
        self._graph.outgoing.pop(loser.id, None)

        # Redirect incoming edges of loser
        for rel_id in list(self._graph.incoming.get(loser.id, [])):
            rel = self._graph.relations.get(rel_id)
            if rel:
                rel.to_id = survivor.id
                self._graph.incoming[survivor.id].append(rel_id)
        self._graph.incoming.pop(loser.id, None)

        # Merge aliases and sources into survivor
        for alias in loser.all_names():
            if alias not in survivor.aliases and alias != survivor.canonical_name:
                survivor.aliases.append(alias)
        survivor.sources = list(set(survivor.sources + loser.sources))
        survivor.confidence = max(survivor.confidence, loser.confidence)

        # Remove loser from graph
        self._indexer.remove_entity(loser)
        self._graph.nodes.pop(loser.id, None)
        self._graph.type_index[loser.entity_type] = [
            i for i in self._graph.type_index[loser.entity_type] if i != loser.id
        ]
        self._graph.domain_index[loser.domain] = [
            i for i in self._graph.domain_index[loser.domain] if i != loser.id
        ]

        # Re-index survivor with merged aliases
        self._indexer.remove_entity(survivor)
        self._indexer.index_entity(survivor)
