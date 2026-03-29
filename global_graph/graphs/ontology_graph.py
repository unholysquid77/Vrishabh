"""
OntologyGraph — in-memory graph store for the global multi-domain graph.
Nodes: BaseEntity. Edges: BaseRelation.
"""

from __future__ import annotations
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from global_graph.core.base_entity import BaseEntity
from global_graph.core.base_relation import BaseRelation


class OntologyGraph:

    def __init__(self):
        self.nodes:      Dict[str, BaseEntity]       = {}   # id → entity
        self.relations:  Dict[str, BaseRelation]      = {}   # id → relation

        # Adjacency
        self.outgoing:   Dict[str, List[str]]         = defaultdict(list)  # from_id → [rel_id]
        self.incoming:   Dict[str, List[str]]         = defaultdict(list)  # to_id   → [rel_id]

        # Indexes
        self.type_index: Dict[str, List[str]]         = defaultdict(list)  # entity_type → [id]
        self.domain_index: Dict[str, List[str]]       = defaultdict(list)  # domain → [id]

    # ── Nodes ─────────────────────────────────────────────────────────────

    def add_node(self, entity: BaseEntity) -> bool:
        """Add node. Returns True if new, False if already existed."""
        if entity.id in self.nodes:
            return False
        self.nodes[entity.id] = entity
        self.type_index[entity.entity_type].append(entity.id)
        self.domain_index[entity.domain].append(entity.id)
        return True

    def update_node(self, entity: BaseEntity):
        """Replace an existing node (keeps edges intact)."""
        old = self.nodes.get(entity.id)
        if old:
            # Remove from old type/domain index
            self.type_index[old.entity_type] = [
                i for i in self.type_index[old.entity_type] if i != entity.id
            ]
            self.domain_index[old.domain] = [
                i for i in self.domain_index[old.domain] if i != entity.id
            ]
        self.nodes[entity.id] = entity
        self.type_index[entity.entity_type].append(entity.id)
        self.domain_index[entity.domain].append(entity.id)

    def get_node(self, node_id: str) -> Optional[BaseEntity]:
        return self.nodes.get(node_id)

    def remove_node(self, node_id: str):
        """Remove node and all its edges."""
        if node_id not in self.nodes:
            return
        entity = self.nodes.pop(node_id)
        self.type_index[entity.entity_type] = [
            i for i in self.type_index[entity.entity_type] if i != node_id
        ]
        self.domain_index[entity.domain] = [
            i for i in self.domain_index[entity.domain] if i != node_id
        ]
        # Remove all connected relations
        for rel_id in list(self.outgoing.get(node_id, [])):
            self._remove_relation(rel_id)
        for rel_id in list(self.incoming.get(node_id, [])):
            self._remove_relation(rel_id)
        self.outgoing.pop(node_id, None)
        self.incoming.pop(node_id, None)

    # ── Relations ─────────────────────────────────────────────────────────

    def add_relation(self, rel: BaseRelation) -> bool:
        """
        Add relation. Deduplicates: if same (from_id, to_id, relation_type) exists,
        keeps higher-confidence version.
        Returns True if added/updated, False if skipped.
        """
        # Check dedup
        existing_id = self._find_duplicate_relation(rel.from_id, rel.to_id, rel.relation_type)
        if existing_id:
            existing = self.relations[existing_id]
            if rel.confidence > existing.confidence:
                # Replace
                self._remove_relation(existing_id)
            else:
                # Skip — existing is equally or more confident
                # But merge sources
                existing.sources = list(set(existing.sources + rel.sources))
                return False

        if rel.from_id not in self.nodes or rel.to_id not in self.nodes:
            return False  # dangling edge

        self.relations[rel.id] = rel
        self.outgoing[rel.from_id].append(rel.id)
        self.incoming[rel.to_id].append(rel.id)
        return True

    def _find_duplicate_relation(self, from_id: str, to_id: str, rel_type: str) -> Optional[str]:
        for rel_id in self.outgoing.get(from_id, []):
            rel = self.relations.get(rel_id)
            if rel and rel.to_id == to_id and rel.relation_type == rel_type:
                return rel_id
        return None

    def _remove_relation(self, rel_id: str):
        rel = self.relations.pop(rel_id, None)
        if not rel:
            return
        self.outgoing[rel.from_id] = [r for r in self.outgoing[rel.from_id] if r != rel_id]
        self.incoming[rel.to_id]   = [r for r in self.incoming[rel.to_id]   if r != rel_id]

    def get_relation(self, rel_id: str) -> Optional[BaseRelation]:
        return self.relations.get(rel_id)

    # ── Traversal ─────────────────────────────────────────────────────────

    def neighbors(self, node_id: str, direction: str = "both") -> List[BaseEntity]:
        """Return neighboring nodes. direction: 'out' | 'in' | 'both'."""
        ids: Set[str] = set()
        if direction in ("out", "both"):
            for rel_id in self.outgoing.get(node_id, []):
                rel = self.relations.get(rel_id)
                if rel:
                    ids.add(rel.to_id)
        if direction in ("in", "both"):
            for rel_id in self.incoming.get(node_id, []):
                rel = self.relations.get(rel_id)
                if rel:
                    ids.add(rel.from_id)
        return [self.nodes[i] for i in ids if i in self.nodes]

    def edges_between(self, from_id: str, to_id: str) -> List[BaseRelation]:
        return [
            self.relations[r]
            for r in self.outgoing.get(from_id, [])
            if self.relations[r].to_id == to_id
        ]

    def multi_hop(self, node_id: str, hops: int = 2) -> Tuple[List[BaseEntity], List[BaseRelation]]:
        """BFS up to `hops` hops from node_id."""
        visited_nodes: Set[str] = {node_id}
        visited_rels:  Set[str] = set()
        frontier = {node_id}

        for _ in range(hops):
            next_frontier: Set[str] = set()
            for nid in frontier:
                for rel_id in list(self.outgoing.get(nid, [])) + list(self.incoming.get(nid, [])):
                    rel = self.relations.get(rel_id)
                    if not rel:
                        continue
                    visited_rels.add(rel_id)
                    for end in (rel.from_id, rel.to_id):
                        if end not in visited_nodes:
                            visited_nodes.add(end)
                            next_frontier.add(end)
            frontier = next_frontier

        nodes = [self.nodes[i] for i in visited_nodes if i in self.nodes]
        rels  = [self.relations[r] for r in visited_rels]
        return nodes, rels

    # ── Stats ─────────────────────────────────────────────────────────────

    def stats(self) -> Dict:
        return {
            "nodes":        len(self.nodes),
            "relations":    len(self.relations),
            "domains":      {d: len(ids) for d, ids in self.domain_index.items()},
            "entity_types": {t: len(ids) for t, ids in self.type_index.items()},
        }
