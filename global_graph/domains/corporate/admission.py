"""
CorporateAdmissionPipeline — BaseRawModel → entities/relations → OntologyGraph.
Handles dedup via EntityResolver and schema sanitization via SchemaRegistry.
"""

from __future__ import annotations
import uuid
from typing import Dict, List, Optional

from global_graph.core.base_entity import BaseEntity
from global_graph.core.base_relation import BaseRelation
from global_graph.domains.base_raw_model import BaseRawModel
from global_graph.domains.corporate.arbiter import CorporateArbiter
from global_graph.domains.corporate.ontology import DOMAIN, CORPORATE_SCHEMA
from global_graph.graphs.graph_repository import GlobalGraphRepository
from global_graph.graphs.schema_registry import SchemaRegistry
from global_graph.utils.entity_resolver import EntityResolver


class CorporateAdmissionPipeline:

    def __init__(
        self,
        repo:     GlobalGraphRepository,
        arbiter:  CorporateArbiter,
        schema:   SchemaRegistry,
        resolver: EntityResolver,
    ):
        self._repo     = repo
        self._arbiter  = arbiter
        self._schema   = schema
        self._resolver = resolver

    def ingest(self, raw: BaseRawModel) -> Dict[str, int]:
        """
        Full pipeline: extract → validate → dedup → admit.
        Returns {"entities": N, "relations": M}.
        """
        extraction = self._arbiter.extract(raw)
        if not extraction:
            return {"entities": 0, "relations": 0}

        # ── Entities ──────────────────────────────────────────────────────
        name_to_id: Dict[str, str] = {}   # canonical_name → node_id (for relation wiring)
        entities_admitted = 0

        for ent_data in extraction.get("entities", []):
            etype = ent_data.get("entity_type", "")
            cname = ent_data.get("canonical_name", "").strip()

            if not cname or not self._schema.valid_entity_type(etype):
                continue

            # Sanitize attributes
            raw_attrs = ent_data.get("attributes", {}) or {}
            attrs     = self._schema.sanitize_attributes(etype, raw_attrs)

            # Try to resolve against existing graph
            existing = self._resolver.resolve(cname, entity_type=etype)
            if existing:
                node_id = existing.id
                # Merge in new info
                for alias in ent_data.get("aliases", []):
                    if alias and alias not in existing.aliases and alias != existing.canonical_name:
                        existing.aliases.append(alias)
                for k, v in attrs.items():
                    if k not in existing.attributes:
                        existing.attributes[k] = v
                existing.sources = list(set(existing.sources + [raw.source_url]))
            else:
                entity = BaseEntity(
                    entity_type    = etype,
                    domain         = DOMAIN,
                    canonical_name = cname,
                    aliases        = ent_data.get("aliases", []),
                    attributes     = attrs,
                    sources        = [raw.source_url],
                    confidence     = float(ent_data.get("confidence", 0.8)),
                )
                node_id = self._repo.add_entity(entity)
                entities_admitted += 1

            name_to_id[cname] = node_id
            # Also map aliases
            for alias in ent_data.get("aliases", []):
                if alias:
                    name_to_id[alias] = node_id

        # ── Relations ─────────────────────────────────────────────────────
        relations_admitted = 0

        for rel_data in extraction.get("relations", []):
            rtype      = rel_data.get("relation_type", "")
            from_name  = rel_data.get("from_entity", "")
            to_name    = rel_data.get("to_entity", "")

            if not self._schema.valid_relation_type(rtype):
                continue

            from_id = name_to_id.get(from_name) or self._resolve_id(from_name)
            to_id   = name_to_id.get(to_name)   or self._resolve_id(to_name)

            if not from_id or not to_id or from_id == to_id:
                continue

            rel = BaseRelation(
                relation_type = rtype,
                from_id       = from_id,
                to_id         = to_id,
                weight        = float(rel_data.get("weight", 0.8)),
                attributes    = rel_data.get("attributes", {}),
                sources       = [raw.source_url],
                confidence    = 0.8,
            )
            if self._repo.add_relation(rel):
                relations_admitted += 1

        return {"entities": entities_admitted, "relations": relations_admitted}

    def _resolve_id(self, name: str) -> Optional[str]:
        e = self._resolver.resolve(name)
        return e.id if e else None
