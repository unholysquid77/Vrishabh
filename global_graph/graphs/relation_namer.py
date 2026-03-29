"""
RelationNamer — names LLM_AFFINITY edges with a short natural-language label.
Stores result in rel.attributes["inferred_relation"].
"""

from __future__ import annotations
import json
from typing import List

from global_graph.core.base_relation import BaseRelation
from global_graph.graphs.ontology_graph import OntologyGraph

BATCH_SIZE = 20


def _edge_snippet(graph: OntologyGraph, rel: BaseRelation) -> str:
    a = graph.nodes.get(rel.from_id)
    b = graph.nodes.get(rel.to_id)
    if not a or not b:
        return ""
    return (
        f"A: {a.canonical_name} [{a.entity_type}/{a.domain}] | "
        f"B: {b.canonical_name} [{b.entity_type}/{b.domain}] | "
        f"weight: {rel.weight:.2f}"
    )


class RelationNamer:

    def __init__(self, graph: OntologyGraph, openai_key: str, model: str = "gpt-4o-mini"):
        self._graph = graph
        self._key   = openai_key
        self._model = model

    def run(self) -> int:
        """
        Name all unnamed LLM_AFFINITY edges.
        Returns number of edges named.
        """
        from openai import OpenAI
        client = OpenAI(api_key=self._key)

        unnamed = [
            rel for rel in self._graph.relations.values()
            if rel.relation_type == "LLM_AFFINITY"
            and "inferred_relation" not in rel.attributes
        ]

        named = 0
        for i in range(0, len(unnamed), BATCH_SIZE):
            batch = unnamed[i: i + BATCH_SIZE]
            named += self._name_batch(client, batch)

        return named

    def _name_batch(self, client, rels: List[BaseRelation]) -> int:
        snippets = []
        valid    = []
        for rel in rels:
            s = _edge_snippet(self._graph, rel)
            if s:
                snippets.append(f"{len(valid)}: {s}")
                valid.append(rel)

        if not snippets:
            return 0

        prompt = (
            "For each numbered entity pair below, write a short (2-5 word) label "
            "describing the relationship from A to B. "
            "Output ONLY a JSON array of strings in the same order. "
            "Examples: 'supplies raw materials to', 'geopolitical rival of', "
            "'climate risk for', 'funded by', 'regulates'.\n\n"
            + "\n".join(snippets)
        )

        try:
            resp = client.chat.completions.create(
                model    = self._model,
                messages = [{"role": "user", "content": prompt}],
                temperature = 0.3,
            )
            raw = resp.choices[0].message.content.strip()
            start  = raw.find("[")
            end    = raw.rfind("]") + 1
            labels = json.loads(raw[start:end])
        except Exception:
            return 0

        named = 0
        for i, rel in enumerate(valid):
            if i < len(labels) and labels[i]:
                rel.attributes["inferred_relation"] = str(labels[i])
                named += 1

        return named
