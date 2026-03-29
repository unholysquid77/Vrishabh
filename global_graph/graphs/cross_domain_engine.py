"""
CrossDomainEngine — LLM-driven typed relation inference between entity domain pairs.

Unlike LLMRelationEngine (which produces generic LLM_AFFINITY edges with a float weight),
this engine produces TYPED, schema-specific relations — e.g. EXPOSED_TO, DISRUPTS,
SANCTIONED_BY — inserted directly into the graph (bypasses SchemaRegistry).

Relations are tagged with attributes["inferred_by"] = "cross_domain_engine".

Usage:
    from global_graph.graphs.cross_domain_engine import CrossDomainEngine, GLOBAL_CROSS_DOMAIN_SCHEMAS
    engine = CrossDomainEngine(graph, openai_key, schemas=GLOBAL_CROSS_DOMAIN_SCHEMAS)
    count  = engine.run(max_pairs_per_schema=30)
"""

from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from global_graph.core.base_entity import BaseEntity
from global_graph.core.base_relation import BaseRelation
from global_graph.graphs.ontology_graph import OntologyGraph


# ── Schema definitions ────────────────────────────────────────────────────────

@dataclass
class CrossDomainSchema:
    """Defines a cross-domain typed relation inference task."""
    from_domain: str
    to_domain:   str
    relations:   List[str]                  # valid relation types for this pair
    from_types:  Optional[List[str]] = None # None = all entity types in from_domain
    to_types:    Optional[List[str]] = None # None = all entity types in to_domain
    description: str                = ""    # LLM context hint


# ── Global graph schemas ───────────────────────────────────────────────────────

GLOBAL_CROSS_DOMAIN_SCHEMAS: List[CrossDomainSchema] = [
    CrossDomainSchema(
        from_domain = "corporate",
        to_domain   = "geopolitics",
        relations   = [
            "EXPOSED_TO", "OPERATES_IN", "SANCTIONED_BY", "BENEFITS_FROM",
            "DISRUPTED_BY", "REGULATES", "IMPACTS_PRICE",
        ],
        from_types  = ["Company", "InvestmentEntity", "CorporateEvent"],
        to_types    = ["Nation", "GovernmentBody", "Sanction", "ConflictEvent", "Alliance"],
        description = "corporate entities affected by or operating within geopolitical contexts",
    ),
    CrossDomainSchema(
        from_domain = "technology",
        to_domain   = "geopolitics",
        relations   = [
            "ENABLES", "RESTRICTED_BY", "DEPLOYED_BY", "FUNDED_BY",
            "BANNED_IN", "ACCELERATES", "USED_IN",
        ],
        from_types  = ["Technology", "ResearchOrg", "TechProgram", "Patent"],
        to_types    = ["Nation", "GovernmentBody", "ConflictEvent"],
        description = "technology entities with geopolitical deployment, restriction, or funding",
    ),
    CrossDomainSchema(
        from_domain = "climate",
        to_domain   = "corporate",
        relations   = [
            "DISRUPTS", "INCREASES_COST_FOR", "THREATENS",
            "CREATES_OPPORTUNITY_FOR", "CONTRIBUTES_TO",
        ],
        from_types  = ["ClimateEvent", "ClimateIndicator", "ClimatePolicy"],
        to_types    = ["Company", "InvestmentEntity"],
        description = "climate events or policies that meaningfully impact corporate entities",
    ),
    CrossDomainSchema(
        from_domain = "technology",
        to_domain   = "corporate",
        relations   = ["DISRUPTS", "ENABLES", "ADOPTED_BY", "THREATENS", "DEVELOPED_BY"],
        from_types  = ["Technology", "Patent"],
        to_types    = ["Company"],
        description = "technology innovations disrupting, enabling, or threatening corporations",
    ),
    CrossDomainSchema(
        from_domain = "climate",
        to_domain   = "geopolitics",
        relations   = [
            "DESTABILIZES", "TRIGGERS_MIGRATION_IN",
            "REDUCES_RESOURCES_OF", "ACCELERATES",
        ],
        from_types  = ["ClimateEvent", "ClimateIndicator"],
        to_types    = ["Nation", "ConflictEvent"],
        description = "climate events that destabilize nations or escalate geopolitical tensions",
    ),
]


# ── India graph schemas ───────────────────────────────────────────────────────

INDIA_CROSS_DOMAIN_SCHEMAS: List[CrossDomainSchema] = [
    CrossDomainSchema(
        from_domain = "india_policy",
        to_domain   = "india_finance",
        relations   = ["REGULATES", "IMPACTS", "ENABLES", "RESTRICTS", "DRIVES"],
        description = "Indian policy decisions (RBI, SEBI, Budget) affecting financial entities",
    ),
    CrossDomainSchema(
        from_domain = "india_policy",
        to_domain   = "india_corporate",
        relations   = ["REGULATES", "SANCTIONS", "APPROVES", "IMPACTS", "BENEFITS"],
        description = "Indian policy affecting corporate entities — Tata, Adani, PSUs, startups",
    ),
    CrossDomainSchema(
        from_domain = "india_economy",
        to_domain   = "india_finance",
        relations   = ["DRIVES", "CORRELATES_WITH", "IMPACTS", "PRESSURES"],
        description = "macroeconomic indicators driving Indian financial market entities",
    ),
    CrossDomainSchema(
        from_domain = "india_economy",
        to_domain   = "india_corporate",
        relations   = ["IMPACTS", "DRIVES_GROWTH_OF", "CONSTRAINS", "CREATES_DEMAND_FOR"],
        description = "macroeconomic trends impacting Indian corporate entities",
    ),
    CrossDomainSchema(
        from_domain = "india_policy",
        to_domain   = "india_economy",
        relations   = ["TARGETS", "AFFECTS", "STIMULATES", "CONSTRAINS"],
        description = "Indian policy decisions targeting or affecting macro-economic indicators",
    ),
]


# ── Engine ────────────────────────────────────────────────────────────────────

_BATCH_SIZE       = 20     # entity pairs per LLM call
_CONFIDENCE_FLOOR = 0.60   # minimum confidence to insert a relation


def _entity_snippet(e: BaseEntity) -> str:
    attrs = ", ".join(f"{k}: {v}" for k, v in list(e.attributes.items())[:3])
    return f"{e.canonical_name} [{e.entity_type}/{e.domain}] ({attrs})"


class CrossDomainEngine:
    """
    Infers typed cross-domain relations using LLM and inserts them into the graph.

    The engine bypasses SchemaRegistry validation (relations are added directly
    to OntologyGraph). Dedup is handled by OntologyGraph.add_relation() itself —
    identical (from_id, to_id, relation_type) triples are merged automatically.
    """

    def __init__(
        self,
        graph:      OntologyGraph,
        openai_key: str,
        schemas:    List[CrossDomainSchema],
        model:      str = "gpt-4o-mini",
    ):
        self._graph   = graph
        self._key     = openai_key
        self._schemas = schemas
        self._model   = model

    def run(self, max_pairs_per_schema: int = 30) -> int:
        """
        Run all schemas. Returns total typed relations inserted.
        """
        from openai import OpenAI
        client   = OpenAI(api_key=self._key)
        inserted = 0
        for schema in self._schemas:
            inserted += self._run_schema(client, schema, max_pairs_per_schema)
        return inserted

    # ── Private ───────────────────────────────────────────────────────────

    def _run_schema(
        self,
        client,
        schema:    CrossDomainSchema,
        max_pairs: int,
    ) -> int:
        from_ents = self._entities_for(schema.from_domain, schema.from_types)
        to_ents   = self._entities_for(schema.to_domain,   schema.to_types)
        if not from_ents or not to_ents:
            return 0

        pairs = self._sample_pairs(from_ents, to_ents, max_pairs)
        if not pairs:
            return 0

        inserted = 0
        for batch_start in range(0, len(pairs), _BATCH_SIZE):
            batch     = pairs[batch_start: batch_start + _BATCH_SIZE]
            inserted += self._score_batch(client, batch, schema)
        return inserted

    def _entities_for(
        self,
        domain:      str,
        type_filter: Optional[List[str]],
    ) -> List[BaseEntity]:
        entities = [e for e in self._graph.nodes.values() if e.domain == domain]
        if type_filter:
            entities = [e for e in entities if e.entity_type in type_filter]
        return entities

    def _sample_pairs(
        self,
        from_ents: List[BaseEntity],
        to_ents:   List[BaseEntity],
        max_pairs: int,
    ) -> List:
        all_pairs = [(a, b) for a in from_ents for b in to_ents if a.id != b.id]
        random.shuffle(all_pairs)
        result = []
        for a, b in all_pairs:
            # Skip pairs that already have ANY direct edge (typed or affinity)
            if (not self._graph.edges_between(a.id, b.id) and
                    not self._graph.edges_between(b.id, a.id)):
                result.append((a, b))
                if len(result) >= max_pairs:
                    break
        return result

    def _score_batch(
        self,
        client,
        pairs:  list,
        schema: CrossDomainSchema,
    ) -> int:
        rel_list = ", ".join(schema.relations)
        lines = [
            f"{i}: A={_entity_snippet(a)} | B={_entity_snippet(b)}"
            for i, (a, b) in enumerate(pairs)
        ]

        prompt = (
            f"You are an expert analyst in global markets, geopolitics, technology, and climate.\n"
            f"Context: {schema.description}\n\n"
            f"For each numbered pair below, determine if entity A has a real, meaningful typed "
            f"relationship with entity B from these options: [{rel_list}].\n\n"
            f"Rules:\n"
            f"- Only confirm relationships that are genuinely meaningful and well-evidenced.\n"
            f"- Confidence must be ≥ {_CONFIDENCE_FLOOR} to be included.\n"
            f"- If no clear relationship exists, use null for relation.\n\n"
            f"Pairs:\n" + "\n".join(lines) + "\n\n"
            f"Return ONLY a JSON array, one entry per pair:\n"
            f'[{{"pair": 0, "relation": "RELATION_TYPE", "confidence": 0.85}}, '
            f'{{"pair": 1, "relation": null}}, ...]'
        )

        try:
            resp = client.chat.completions.create(
                model       = self._model,
                messages    = [{"role": "user", "content": prompt}],
                temperature = 0.0,
            )
            raw   = resp.choices[0].message.content.strip()
            start = raw.find("[")
            end   = raw.rfind("]") + 1
            items = json.loads(raw[start:end])
        except Exception:
            return 0

        inserted = 0
        for item in items:
            try:
                pair_idx = int(item.get("pair", -1))
                rel_type = item.get("relation")
                conf     = float(item.get("confidence") or 0.0)
            except (TypeError, ValueError, KeyError):
                continue

            if rel_type is None or conf < _CONFIDENCE_FLOOR:
                continue
            if pair_idx < 0 or pair_idx >= len(pairs):
                continue
            if rel_type not in schema.relations:
                continue  # hallucinated relation type — reject

            a, b = pairs[pair_idx]
            rel = BaseRelation(
                id            = str(uuid.uuid4()),
                relation_type = rel_type,
                from_id       = a.id,
                to_id         = b.id,
                weight        = conf,
                attributes    = {"inferred_by": "cross_domain_engine"},
                sources       = [],
                confidence    = conf,
            )
            if self._graph.add_relation(rel):
                inserted += 1

        return inserted
