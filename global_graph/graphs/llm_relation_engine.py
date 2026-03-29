"""
LLMRelationEngine — batched LLM inference of cross-entity affinities.
Inserts LLM_AFFINITY meta-relations (weight threshold 0.15).
"""

from __future__ import annotations
import json
import uuid
from typing import List, Optional

from global_graph.core.base_entity import BaseEntity
from global_graph.core.base_relation import BaseRelation
from global_graph.graphs.ontology_graph import OntologyGraph

WEIGHT_THRESHOLD = 0.15
BATCH_SIZE       = 12    # entities per LLM call


def _entity_snippet(e: BaseEntity) -> str:
    attrs = ", ".join(f"{k}: {v}" for k, v in list(e.attributes.items())[:3])
    return f"{e.canonical_name} [{e.entity_type}/{e.domain}] ({attrs})"


class LLMRelationEngine:

    def __init__(self, graph: OntologyGraph, openai_key: str, model: str = "gpt-4o-mini"):
        self._graph = graph
        self._key   = openai_key
        self._model = model

    def run(self, max_pairs: int = 200) -> int:
        """
        Score random sample of entity pairs and insert LLM_AFFINITY edges.
        Returns number of edges inserted.
        """
        from openai import OpenAI
        client = OpenAI(api_key=self._key)

        entities = list(self._graph.nodes.values())
        # Cross-domain pairs are most interesting
        pairs = self._candidate_pairs(entities, max_pairs)
        if not pairs:
            return 0

        inserted = 0
        for batch_start in range(0, len(pairs), BATCH_SIZE):
            batch = pairs[batch_start: batch_start + BATCH_SIZE]
            inserted += self._score_batch(client, batch)

        return inserted

    def _candidate_pairs(self, entities: List[BaseEntity], max_pairs: int):
        """
        Sample cross-domain pairs that don't already have a direct edge.
        """
        import random
        cross = [(a, b) for i, a in enumerate(entities)
                         for b in entities[i+1:]
                         if a.domain != b.domain]
        random.shuffle(cross)
        # Filter out already-connected
        result = []
        for a, b in cross:
            if not self._graph.edges_between(a.id, b.id) and \
               not self._graph.edges_between(b.id, a.id):
                result.append((a, b))
                if len(result) >= max_pairs:
                    break
        return result

    def _score_batch(self, client, pairs: list) -> int:
        snippets = []
        for i, (a, b) in enumerate(pairs):
            snippets.append(f"{i}: A={_entity_snippet(a)} | B={_entity_snippet(b)}")

        prompt = (
            "You are an expert in global affairs, finance, geopolitics, climate, and technology.\n"
            "For each numbered pair below, estimate the strength of any meaningful connection "
            "(0.0 = unrelated, 1.0 = very strongly connected).\n"
            "Output ONLY a JSON array of floats in the same order.\n\n"
            + "\n".join(snippets)
        )

        try:
            resp = client.chat.completions.create(
                model    = self._model,
                messages = [{"role": "user", "content": prompt}],
                temperature = 0.0,
            )
            raw = resp.choices[0].message.content.strip()
            # Extract JSON array
            start = raw.find("[")
            end   = raw.rfind("]") + 1
            scores = json.loads(raw[start:end])
        except Exception:
            return 0

        inserted = 0
        for i, (a, b) in enumerate(pairs):
            if i >= len(scores):
                break
            try:
                weight = float(scores[i])
            except (TypeError, ValueError):
                continue
            if weight >= WEIGHT_THRESHOLD:
                rel = BaseRelation(
                    id            = str(uuid.uuid4()),
                    relation_type = "LLM_AFFINITY",
                    from_id       = a.id,
                    to_id         = b.id,
                    weight        = weight,
                    attributes    = {},
                    sources       = [],
                    confidence    = 0.7,
                )
                if self._graph.add_relation(rel):
                    inserted += 1

        return inserted
