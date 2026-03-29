import json
import math
import os
from collections import defaultdict
from typing import List, Optional

from openai import OpenAI

from .entities import FinanceEntity, EntityType
from .relations import FinanceRelation
from .finance_graph import FinanceGraph


class GraphRepository:
    """
    Persistence, search, and traversal facade over FinanceGraph.
    Also owns the semantic embedding index for expose() queries.
    """

    def __init__(self, graph: FinanceGraph, file_path: str, openai_key: Optional[str] = None):
        self.graph     = graph
        self.file_path = file_path

        self._openai = OpenAI(api_key=openai_key) if openai_key else None

        # Lazy embedding index: node_id → vector
        self._embed_index:      dict = {}
        self._embed_index_size: int  = 0

    # ──────────────────────────────────────────
    # PERSISTENCE
    # ──────────────────────────────────────────

    def save(self):
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        data = {
            "nodes": {
                nid: node.model_dump(mode="json")
                for nid, node in self.graph.nodes.items()
            },
            "relations": {
                rid: rel.model_dump(mode="json")
                for rid, rel in self.graph.relations.items()
            },
            "type_index":   {k: list(v) for k, v in self.graph.type_index.items()},
            "ticker_index": {k: list(v) for k, v in self.graph.ticker_index.items()},
            "outgoing":     {k: list(v) for k, v in self.graph.outgoing.items()},
            "incoming":     {k: list(v) for k, v in self.graph.incoming.items()},
        }
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def load(self):
        if not os.path.exists(self.file_path):
            return

        with open(self.file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.graph.nodes = {
            nid: FinanceEntity(**nd)
            for nid, nd in data.get("nodes", {}).items()
        }
        self.graph.relations = {
            rid: FinanceRelation(**rd)
            for rid, rd in data.get("relations", {}).items()
        }
        self.graph.type_index = defaultdict(set, {
            k: set(v) for k, v in data.get("type_index", {}).items()
        })
        self.graph.ticker_index = defaultdict(set, {
            k: set(v) for k, v in data.get("ticker_index", {}).items()
        })
        self.graph.outgoing = defaultdict(set, {
            k: set(v) for k, v in data.get("outgoing", {}).items()
        })
        self.graph.incoming = defaultdict(set, {
            k: set(v) for k, v in data.get("incoming", {}).items()
        })

    # ──────────────────────────────────────────
    # SEARCH
    # ──────────────────────────────────────────

    def find_by_ticker(self, ticker: str) -> List[FinanceEntity]:
        return self.graph.get_by_ticker(ticker)

    def find_company(self, ticker: str) -> Optional[FinanceEntity]:
        return self.graph.get_company_node(ticker)

    def search_partial(self, text: str, limit: int = 20) -> List[FinanceEntity]:
        """Case-insensitive substring search across canonical_name and aliases."""
        text = text.lower()
        results = []
        for node in self.graph.nodes.values():
            if text in node.canonical_name.lower():
                results.append(node)
                continue
            if any(text in a.lower() for a in node.aliases):
                results.append(node)
        return results[:limit]

    def get_by_type(self, ontology_type: str) -> List[FinanceEntity]:
        return self.graph.get_by_type(ontology_type)

    # ──────────────────────────────────────────
    # TRAVERSAL
    # ──────────────────────────────────────────

    def one_hop(self, node_id: str):
        return self.graph.one_hop(node_id)

    def multi_hop(self, node_id: str, depth: int = 2):
        return self.graph.multi_hop(node_id, depth)

    def get_company_graph(self, ticker: str) -> dict:
        """
        Returns all entities and relations connected to a company within 2 hops.
        Used for graph visualization.
        """
        company = self.find_company(ticker)
        if not company:
            return {"nodes": [], "relations": []}

        seen_nodes = {company.id: self._serialize_entity(company)}
        seen_rels  = {}

        for node_id, rel, tgt_id, _ in self.graph.multi_hop(company.id, depth=2):
            tgt = self.graph.get_node(tgt_id)
            if tgt and tgt_id not in seen_nodes:
                seen_nodes[tgt_id] = self._serialize_entity(tgt)
            if rel.id not in seen_rels:
                seen_rels[rel.id] = self._serialize_relation(rel)

        # also grab direct incoming edges (who mentions/tracks this company)
        for rel in self.graph.get_relations_to(company.id):
            src = self.graph.get_node(rel.from_node_id)
            if src and src.id not in seen_nodes:
                seen_nodes[src.id] = self._serialize_entity(src)
            if rel.id not in seen_rels:
                seen_rels[rel.id] = self._serialize_relation(rel)

        return {
            "nodes":     list(seen_nodes.values()),
            "relations": list(seen_rels.values()),
        }

    def full_graph_data(self) -> dict:
        """All nodes + relations serialized for vis.js."""
        return {
            "nodes":     [self._serialize_entity(n) for n in self.graph.nodes.values()],
            "relations": [self._serialize_relation(r) for r in self.graph.relations.values()],
        }

    # ──────────────────────────────────────────
    # SEMANTIC SEARCH (embedding-based)
    # ──────────────────────────────────────────

    def expose(self, tags: List[str], top_k: int = 20, threshold: float = 0.35) -> List[FinanceEntity]:
        """
        Semantically find entities related to a list of tags/keywords.
        Falls back to keyword search if OpenAI client is unavailable.
        """
        if not self._openai:
            return self._keyword_search(tags, top_k)

        self._refresh_embed_index()

        if not self._embed_index:
            return self._keyword_search(tags, top_k)

        query_vec = self._embed([" | ".join(tags)])[0]
        if not query_vec:
            return self._keyword_search(tags, top_k)

        scored = []
        for nid, vec in self._embed_index.items():
            node = self.graph.nodes.get(nid)
            if not node:
                continue
            score = self._cosine(query_vec, vec)
            if score >= threshold:
                scored.append((score, node))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [n for _, n in scored[:top_k]]

    def _keyword_search(self, tags: List[str], limit: int) -> List[FinanceEntity]:
        tags_lower = [t.lower() for t in tags]
        scored = []
        for node in self.graph.nodes.values():
            blob = " ".join([
                node.canonical_name.lower(),
                " ".join(node.aliases).lower(),
                node.ontology_type.lower(),
                (node.description or "").lower(),
                " ".join(str(v).lower() for v in node.attributes.values() if isinstance(v, (str, int, float))),
            ])
            score = sum(1 for t in tags_lower if t in blob)
            if score > 0:
                scored.append((score, node))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [n for _, n in scored[:limit]]

    def _refresh_embed_index(self):
        current_size = len(self.graph.nodes)
        if current_size == self._embed_index_size:
            return

        unindexed = [nid for nid in self.graph.nodes if nid not in self._embed_index]
        if not unindexed:
            self._embed_index_size = current_size
            return

        texts   = [self._node_text(self.graph.nodes[nid]) for nid in unindexed]
        vectors = self._embed(texts)

        for nid, vec in zip(unindexed, vectors):
            self._embed_index[nid] = vec

        self._embed_index_size = current_size

    def _node_text(self, node: FinanceEntity) -> str:
        parts = [node.canonical_name, node.ontology_type]
        if node.ticker:
            parts.append(node.ticker)
        parts.extend(node.aliases)
        if node.description:
            parts.append(node.description)
        for v in node.attributes.values():
            if isinstance(v, (str, int, float)) and v:
                parts.append(str(v))
        return " | ".join(p for p in parts if p)

    def _embed(self, texts: List[str]) -> List[List[float]]:
        if not self._openai or not texts:
            return [[] for _ in texts]
        BATCH = 512
        all_vecs = []
        for i in range(0, len(texts), BATCH):
            batch = texts[i:i + BATCH]
            resp  = self._openai.embeddings.create(model="text-embedding-3-small", input=batch)
            all_vecs.extend([d.embedding for d in resp.data])
        return all_vecs

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        if not a or not b:
            return 0.0
        dot   = sum(x * y for x, y in zip(a, b))
        mag_a = math.sqrt(sum(x * x for x in a))
        mag_b = math.sqrt(sum(x * x for x in b))
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return dot / (mag_a * mag_b)

    # ──────────────────────────────────────────
    # SERIALIZERS
    # ──────────────────────────────────────────

    def _serialize_entity(self, node: FinanceEntity) -> dict:
        d = node.model_dump(mode="json")
        d["name"] = node.canonical_name
        return d

    def _serialize_relation(self, rel: FinanceRelation) -> dict:
        return rel.model_dump(mode="json")

    # ──────────────────────────────────────────
    # SUMMARY
    # ──────────────────────────────────────────

    def summary(self) -> dict:
        return self.graph.summary()
