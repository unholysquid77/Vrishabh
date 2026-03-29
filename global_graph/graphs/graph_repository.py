"""
GlobalGraphRepository — persistence, search, and vis-data export
for the global multi-domain OntologyGraph.
"""

from __future__ import annotations
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from global_graph.core.base_entity import BaseEntity
from global_graph.core.base_relation import BaseRelation
from global_graph.graphs.ontology_graph import OntologyGraph
from global_graph.graphs.entity_indexer import EntityIndexer
from global_graph.graphs.schema_registry import SchemaRegistry

# Domain → vis color
DOMAIN_COLORS = {
    "corporate":   "#3B82F6",   # blue
    "geopolitics": "#EF4444",   # red
    "climate":     "#22C55E",   # green
    "technology":  "#A855F7",   # purple
    "meta":        "#F59E0B",   # amber
}
DEFAULT_COLOR  = "#6B7280"


class GlobalGraphRepository:

    def __init__(
        self,
        graph:    OntologyGraph,
        file_path: str,
        schema:   Optional[SchemaRegistry] = None,
        openai_key: str = "",
    ):
        self._graph     = graph
        self._file_path = file_path
        self._schema    = schema or SchemaRegistry()
        self._indexer   = EntityIndexer(graph)
        self._openai_key = openai_key

    # ── Persistence ───────────────────────────────────────────────────────

    def save(self):
        os.makedirs(os.path.dirname(self._file_path), exist_ok=True)
        data = {
            "nodes":     [e.to_dict() for e in self._graph.nodes.values()],
            "relations": [r.to_dict() for r in self._graph.relations.values()],
        }
        with open(self._file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self):
        if not os.path.exists(self._file_path):
            return
        with open(self._file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for nd in data.get("nodes", []):
            entity = BaseEntity.from_dict(nd)
            self._graph.add_node(entity)
        for rd in data.get("relations", []):
            rel = BaseRelation.from_dict(rd)
            self._graph.add_relation(rel)
        self._indexer.rebuild()

    # ── Admission ─────────────────────────────────────────────────────────

    def add_entity(self, entity: BaseEntity) -> str:
        """
        Add or merge entity. Returns the surviving node_id.
        Uses EntityResolver-style lookup before inserting.
        """
        # Try exact index match first
        matches = self._indexer.lookup(entity.canonical_name)
        for mid in matches:
            existing = self._graph.nodes.get(mid)
            if existing and existing.entity_type == entity.entity_type:
                # Merge into existing
                for alias in entity.all_names():
                    if alias not in existing.aliases and alias != existing.canonical_name:
                        existing.aliases.append(alias)
                existing.sources = list(set(existing.sources + entity.sources))
                existing.confidence = max(existing.confidence, entity.confidence)
                for k, v in entity.attributes.items():
                    if k not in existing.attributes:
                        existing.attributes[k] = v
                self._indexer.index_entity(existing)
                return existing.id

        self._graph.add_node(entity)
        self._indexer.index_entity(entity)
        return entity.id

    def add_relation(self, rel: BaseRelation) -> bool:
        return self._graph.add_relation(rel)

    # ── Search ────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 15) -> List[BaseEntity]:
        """Partial name search across all entities."""
        q = query.lower()
        results = []
        for entity in self._graph.nodes.values():
            for name in entity.all_names():
                if q in name.lower():
                    results.append(entity)
                    break
        return sorted(results, key=lambda e: e.confidence, reverse=True)[:limit]

    def search_by_domain(self, domain: str) -> List[BaseEntity]:
        return [
            self._graph.nodes[i]
            for i in self._graph.domain_index.get(domain, [])
            if i in self._graph.nodes
        ]

    def search_by_type(self, entity_type: str) -> List[BaseEntity]:
        return [
            self._graph.nodes[i]
            for i in self._graph.type_index.get(entity_type, [])
            if i in self._graph.nodes
        ]

    def get_entity(self, node_id: str) -> Optional[BaseEntity]:
        return self._graph.get_node(node_id)

    def resolve(self, name: str, entity_type: Optional[str] = None) -> Optional[BaseEntity]:
        """Best-effort name → entity resolution."""
        candidates = self._indexer.lookup(name)
        for cid in candidates:
            e = self._graph.nodes.get(cid)
            if e:
                if entity_type is None or e.entity_type == entity_type:
                    return e
        # Fallback: substring
        for e in self._graph.nodes.values():
            for n in e.all_names():
                if name.lower() in n.lower() or n.lower() in name.lower():
                    if entity_type is None or e.entity_type == entity_type:
                        return e
        return None

    # ── Subgraph / Vis ────────────────────────────────────────────────────

    def entity_subgraph(self, node_id: str, hops: int = 2) -> Dict[str, Any]:
        """Return vis.js-compatible subgraph."""
        nodes, rels = self._graph.multi_hop(node_id, hops)
        return self._to_vis(nodes, rels)

    def full_graph_data(self) -> Dict[str, Any]:
        """Full graph for vis.js, capped at 500 nodes for performance."""
        entities  = list(self._graph.nodes.values())[:500]
        node_ids  = {e.id for e in entities}
        relations = [
            r for r in self._graph.relations.values()
            if r.from_id in node_ids and r.to_id in node_ids
        ]
        return self._to_vis(entities, relations)

    def _to_vis(self, entities: List[BaseEntity], relations: List[BaseRelation]) -> Dict:
        vis_nodes = []
        for e in entities:
            color = DOMAIN_COLORS.get(e.domain, DEFAULT_COLOR)
            label = e.canonical_name
            if len(label) > 22:
                label = label[:20] + "…"
            vis_nodes.append({
                "id":     e.id,
                "label":  label,
                "title":  e.summary(),
                "group":  e.domain,
                "color":  {"background": color, "border": color},
                "font":   {"color": "#F8FAFC", "face": "JetBrains Mono"},
                "domain": e.domain,
                "type":   e.entity_type,
            })

        vis_edges = []
        for r in relations:
            label = r.attributes.get("inferred_relation", r.relation_type.replace("_", " ").lower())
            vis_edges.append({
                "id":     r.id,
                "from":   r.from_id,
                "to":     r.to_id,
                "label":  label,
                "weight": r.weight,
                "title":  f"{r.relation_type} (w={r.weight:.2f})",
                "arrows": "to",
                "color":  {"color": "#334155", "highlight": "#64748B"},
                "font":   {"color": "#94A3B8", "size": 10, "face": "JetBrains Mono"},
            })

        return {"nodes": vis_nodes, "edges": vis_edges}

    # ── Semantic search ───────────────────────────────────────────────────

    def semantic_search(self, query: str, limit: int = 10) -> List[BaseEntity]:
        """
        Embed query and find closest entities by cosine similarity.
        Falls back to keyword search if OpenAI key unavailable.
        """
        if not self._openai_key:
            return self.search(query, limit)
        try:
            from openai import OpenAI
            import numpy as np
            client = OpenAI(api_key=self._openai_key)

            # Build entity corpus (lazily cached)
            entities  = list(self._graph.nodes.values())
            texts     = [f"{e.canonical_name} {e.entity_type} {e.domain} "
                         + " ".join(str(v) for v in e.attributes.values()) for e in entities]

            resp = client.embeddings.create(
                model = "text-embedding-3-small",
                input = [query] + texts,
            )
            vecs     = np.array([d.embedding for d in resp.data])
            q_vec    = vecs[0]
            e_vecs   = vecs[1:]
            norms    = np.linalg.norm(e_vecs, axis=1, keepdims=True) + 1e-9
            e_vecs   = e_vecs / norms
            q_norm   = q_vec / (np.linalg.norm(q_vec) + 1e-9)
            scores   = e_vecs @ q_norm
            top_idx  = np.argsort(scores)[::-1][:limit]
            return [entities[i] for i in top_idx]
        except Exception:
            return self.search(query, limit)

    # ── Summary ───────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        return self._graph.stats()
