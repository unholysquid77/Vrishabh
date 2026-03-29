import math
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Set

from .entities import FinanceEntity
from .relations import FinanceRelation


class FinanceGraph:
    """
    In-memory finance knowledge graph.

    Nodes  : FinanceEntity
    Edges  : FinanceRelation
    Indexes: domain, type, ticker → fast O(1) lookups
    """

    def __init__(self):
        # Core storage
        self.nodes:     Dict[str, FinanceEntity]  = {}
        self.relations: Dict[str, FinanceRelation] = {}

        # Indexes
        self.type_index:   Dict[str, Set[str]] = defaultdict(set)   # ontology_type → {node_id}
        self.ticker_index: Dict[str, Set[str]] = defaultdict(set)   # ticker → {node_id}

        # Adjacency
        self.outgoing: Dict[str, Set[str]] = defaultdict(set)       # node_id → {relation_id}
        self.incoming: Dict[str, Set[str]] = defaultdict(set)       # node_id → {relation_id}

    # ──────────────────────────────────────────
    # NODE CRUD
    # ──────────────────────────────────────────

    def add_node(self, node: FinanceEntity) -> str:
        if node.id in self.nodes:
            return node.id  # idempotent

        self.nodes[node.id] = node
        self.type_index[node.ontology_type].add(node.id)

        if node.ticker:
            self.ticker_index[node.ticker.upper()].add(node.id)

        return node.id

    def update_node(self, node_id: str, updated: FinanceEntity):
        if node_id not in self.nodes:
            raise KeyError(f"Node {node_id} not found.")

        old = self.nodes[node_id]
        # remove old ticker index entry
        if old.ticker:
            self.ticker_index[old.ticker.upper()].discard(node_id)

        self.nodes[node_id] = updated
        self.type_index[updated.ontology_type].add(node_id)

        if updated.ticker:
            self.ticker_index[updated.ticker.upper()].add(node_id)

    def get_node(self, node_id: str) -> Optional[FinanceEntity]:
        return self.nodes.get(node_id)

    def get_by_type(self, ontology_type: str) -> List[FinanceEntity]:
        return [self.nodes[nid] for nid in self.type_index.get(ontology_type, []) if nid in self.nodes]

    def get_by_ticker(self, ticker: str) -> List[FinanceEntity]:
        ticker = ticker.upper()
        return [self.nodes[nid] for nid in self.ticker_index.get(ticker, []) if nid in self.nodes]

    def get_company_node(self, ticker: str) -> Optional[FinanceEntity]:
        from .entities import EntityType
        ticker = ticker.upper()
        for node in self.get_by_ticker(ticker):
            if node.ontology_type == EntityType.COMPANY:
                return node
        return None

    # ──────────────────────────────────────────
    # RELATION CRUD
    # ──────────────────────────────────────────

    def add_relation(self, relation: FinanceRelation) -> str:
        if relation.id in self.relations:
            return relation.id

        if relation.from_node_id not in self.nodes or relation.to_node_id not in self.nodes:
            raise KeyError("Relation references non-existent node.")

        # Deduplicate: same type + same endpoints → skip
        for rid in list(self.outgoing.get(relation.from_node_id, [])):
            existing = self.relations.get(rid)
            if not existing:
                self.outgoing[relation.from_node_id].discard(rid)
                continue
            if (
                existing.to_node_id   == relation.to_node_id
                and existing.relation_type == relation.relation_type
            ):
                return existing.id

        self.relations[relation.id] = relation
        self.outgoing[relation.from_node_id].add(relation.id)
        self.incoming[relation.to_node_id].add(relation.id)

        return relation.id

    def get_relations_from(self, node_id: str) -> List[FinanceRelation]:
        return [
            self.relations[rid]
            for rid in self.outgoing.get(node_id, [])
            if rid in self.relations
        ]

    def get_relations_to(self, node_id: str) -> List[FinanceRelation]:
        return [
            self.relations[rid]
            for rid in self.incoming.get(node_id, [])
            if rid in self.relations
        ]

    # ──────────────────────────────────────────
    # TRAVERSAL
    # ──────────────────────────────────────────

    def one_hop(self, node_id: str):
        """Returns list of (relation, target_node, effective_weight)."""
        results = []
        for rel in self.get_relations_from(node_id):
            target = self.get_node(rel.to_node_id)
            if target:
                weight = self._effective_weight(rel)
                results.append((rel, target, weight))
        return results

    def multi_hop(self, start_id: str, depth: int = 2):
        """Returns list of (src_id, relation, tgt_id, weight)."""
        visited  = set()
        frontier = {start_id}
        results  = []

        for _ in range(depth):
            next_frontier = set()
            for node_id in frontier:
                for rel in self.get_relations_from(node_id):
                    tgt = rel.to_node_id
                    if tgt not in visited:
                        visited.add(tgt)
                        next_frontier.add(tgt)
                        results.append((node_id, rel, tgt, self._effective_weight(rel)))
            frontier = next_frontier

        return results

    def _effective_weight(self, rel: FinanceRelation, half_life_days: float = 180.0) -> float:
        """Time-decay * confidence weight."""
        delta = (datetime.utcnow() - rel.created_at).days
        decay = math.exp(-math.log(2) * delta / half_life_days)
        return rel.weight * decay * rel.confidence

    # ──────────────────────────────────────────
    # STATS
    # ──────────────────────────────────────────

    def summary(self) -> dict:
        return {
            "total_nodes":     len(self.nodes),
            "total_relations": len(self.relations),
            "types":           {t: len(ids) for t, ids in self.type_index.items()},
            "tickers_tracked": len(self.ticker_index),
        }
