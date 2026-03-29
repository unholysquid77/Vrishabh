"""
GlobalGraphOrchestrator — full pipeline driver for the global intelligence graph.

Pipeline per run:
  1. Ingest articles from all 4 domain ingestors
  2. Run domain arbiters + admission pipelines
  3. GraphDedup pass
  4. Cross-domain typed relation engine
  5. LLMRelationEngine cross-domain affinity pass
  6. RelationNamer pass
  7. Save graph to disk
"""

from __future__ import annotations
import os
from datetime import datetime
from typing import Callable, Dict, Optional

from global_graph.core.base_entity import BaseEntity
from global_graph.graphs.ontology_graph import OntologyGraph
from global_graph.graphs.graph_repository import GlobalGraphRepository
from global_graph.graphs.schema_registry import SchemaRegistry
from global_graph.graphs.graph_dedup import GraphDedup
from global_graph.graphs.llm_relation_engine import LLMRelationEngine
from global_graph.graphs.relation_namer import RelationNamer
from global_graph.graphs.cross_domain_engine import CrossDomainEngine, GLOBAL_CROSS_DOMAIN_SCHEMAS
from global_graph.utils.model_client import ModelClient
from global_graph.utils.entity_resolver import EntityResolver

# Domains
from global_graph.domains.corporate.ontology import CORPORATE_SCHEMA, CORPORATE_RELATIONS
from global_graph.domains.corporate.arbiter import CorporateArbiter
from global_graph.domains.corporate.admission import CorporateAdmissionPipeline

from global_graph.domains.geopolitics.ontology import GEOPOLITICS_SCHEMA, GEOPOLITICS_RELATIONS
from global_graph.domains.geopolitics.arbiter import GeopoliticsArbiter
from global_graph.domains.geopolitics.admission import GeopoliticsAdmissionPipeline

from global_graph.domains.climate.ontology import CLIMATE_SCHEMA, CLIMATE_RELATIONS
from global_graph.domains.climate.arbiter import ClimateArbiter
from global_graph.domains.climate.admission import ClimateAdmissionPipeline

from global_graph.domains.technology.ontology import TECHNOLOGY_SCHEMA, TECHNOLOGY_RELATIONS
from global_graph.domains.technology.arbiter import TechnologyArbiter
from global_graph.domains.technology.admission import TechnologyAdmissionPipeline

# Ingestors
from global_graph.ingestors.corporate_ingestor import CorporateIngestor
from global_graph.ingestors.geopolitics_ingestor import GeopoliticsIngestor
from global_graph.ingestors.climate_ingestor import ClimateIngestor
from global_graph.ingestors.technology_ingestor import TechnologyIngestor


LOG = Callable[[str], None]


class GlobalGraphOrchestrator:

    def __init__(
        self,
        openai_key:     str,
        newsdata_key:   str,
        graph_file:     str,
        log_callback:   Optional[LOG] = None,
        max_articles_per_domain: int  = 40,
        affinity_pairs: int           = 150,
        acled_email:    str           = "",
        acled_password: str           = "",
    ):
        self._openai_key    = openai_key
        self._newsdata_key  = newsdata_key
        self._graph_file    = graph_file
        self._log           = log_callback or print
        self._max_articles  = max_articles_per_domain
        self._affinity_pairs = affinity_pairs
        self._acled_email   = acled_email
        self._acled_password = acled_password

        # ── Build core objects ────────────────────────────────────────────
        self._graph    = OntologyGraph()
        self._schema   = self._build_schema()
        self._repo     = GlobalGraphRepository(
            graph      = self._graph,
            file_path  = self._graph_file,
            schema     = self._schema,
            openai_key = self._openai_key,
        )
        self._indexer  = self._repo._indexer
        self._resolver = EntityResolver(self._graph, self._indexer)
        self._model    = ModelClient(self._openai_key)

        # ── Domain pipelines ──────────────────────────────────────────────
        self._corp_pipeline = CorporateAdmissionPipeline(
            self._repo, CorporateArbiter(self._model), self._schema, self._resolver
        )
        self._geo_pipeline = GeopoliticsAdmissionPipeline(
            self._repo, GeopoliticsArbiter(self._model), self._schema, self._resolver
        )
        self._cli_pipeline = ClimateAdmissionPipeline(
            self._repo, ClimateArbiter(self._model), self._schema, self._resolver
        )
        self._tech_pipeline = TechnologyAdmissionPipeline(
            self._repo, TechnologyArbiter(self._model), self._schema, self._resolver
        )

        # ── Ingestors ─────────────────────────────────────────────────────
        self._corp_ingestor = CorporateIngestor(self._newsdata_key)
        self._geo_ingestor  = GeopoliticsIngestor(
            self._newsdata_key,
            acled_email    = self._acled_email,
            acled_password = self._acled_password,
        )
        self._cli_ingestor  = ClimateIngestor(self._newsdata_key)
        self._tech_ingestor = TechnologyIngestor(self._newsdata_key)

    # ── Schema init ───────────────────────────────────────────────────────

    def _build_schema(self) -> SchemaRegistry:
        schema = SchemaRegistry()
        schema.register_domain("corporate",   CORPORATE_SCHEMA,   CORPORATE_RELATIONS)
        schema.register_domain("geopolitics", GEOPOLITICS_SCHEMA, GEOPOLITICS_RELATIONS)
        schema.register_domain("climate",     CLIMATE_SCHEMA,     CLIMATE_RELATIONS)
        schema.register_domain("technology",  TECHNOLOGY_SCHEMA,  TECHNOLOGY_RELATIONS)
        return schema

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def repo(self) -> GlobalGraphRepository:
        return self._repo

    @property
    def graph(self) -> OntologyGraph:
        return self._graph

    def load(self):
        """Load persisted graph from disk."""
        self._repo.load()
        self._log(f"[GlobalGraph] Loaded: {self._repo.summary()}")

    def run(self) -> Dict[str, int]:
        """
        Full ingestion + enrichment pipeline.
        Returns stats dict.
        """
        run_ts = datetime.utcnow().isoformat()
        stats: Dict[str, int] = {
            "corporate_entities": 0, "corporate_relations": 0,
            "geopolitics_entities": 0, "geopolitics_relations": 0,
            "climate_entities": 0, "climate_relations": 0,
            "technology_entities": 0, "technology_relations": 0,
            "dedup_merges": 0,
            "affinity_edges": 0,
            "cross_domain_relations": 0,
            "relations_named": 0,
        }

        node_before = len(self._graph.nodes)
        rel_before  = len(self._graph.relations)
        self._log(f"[GlobalGraph] Starting run at {run_ts} — graph has {node_before} nodes, {rel_before} relations")

        # ── 1. Ingest + Admit ─────────────────────────────────────────────
        for domain, ingestor, pipeline, key_prefix in [
            ("corporate",   self._corp_ingestor,  self._corp_pipeline,  "corporate"),
            ("geopolitics", self._geo_ingestor,   self._geo_pipeline,   "geopolitics"),
            ("climate",     self._cli_ingestor,   self._cli_pipeline,   "climate"),
            ("technology",  self._tech_ingestor,  self._tech_pipeline,  "technology"),
        ]:
            self._log(f"[GlobalGraph] ── Ingesting {domain} ──")
            try:
                articles = ingestor.fetch(max_articles=self._max_articles)
                self._log(f"[GlobalGraph] {domain}: {len(articles)} raw items fetched")
                admitted = 0
                for i, raw in enumerate(articles, 1):
                    result = pipeline.ingest(raw)
                    e = result["entities"]
                    r = result["relations"]
                    stats[f"{key_prefix}_entities"]  += e
                    stats[f"{key_prefix}_relations"] += r
                    admitted += e
                    if e > 0:
                        self._log(f"[GlobalGraph] {domain} [{i}/{len(articles)}] admitted {e}e {r}r — '{(raw.title or raw.text[:60]).strip()}'")
                self._log(
                    f"[GlobalGraph] {domain} done: "
                    f"+{stats[f'{key_prefix}_entities']} entities, "
                    f"+{stats[f'{key_prefix}_relations']} relations "
                    f"({admitted} items produced entities)"
                )
            except Exception as e:
                self._log(f"[GlobalGraph] {domain} ERROR: {e}")

        total_new_nodes = len(self._graph.nodes) - node_before
        total_new_rels  = len(self._graph.relations) - rel_before
        self._log(f"[GlobalGraph] Ingestion complete: +{total_new_nodes} nodes, +{total_new_rels} relations")

        # ── 2. Dedup ──────────────────────────────────────────────────────
        self._log("[GlobalGraph] ── Running dedup pass ──")
        dedup = GraphDedup(self._graph, self._indexer)
        stats["dedup_merges"] = dedup.run()
        self._log(f"[GlobalGraph] Dedup merged {stats['dedup_merges']} nodes → {len(self._graph.nodes)} total")

        # ── 3. Cross-domain typed relations ───────────────────────────────
        self._log("[GlobalGraph] ── Running cross-domain typed relation engine ──")
        try:
            cross_engine = CrossDomainEngine(
                graph      = self._graph,
                openai_key = self._openai_key,
                schemas    = GLOBAL_CROSS_DOMAIN_SCHEMAS,
            )
            stats["cross_domain_relations"] = cross_engine.run(max_pairs_per_schema=30)
            self._log(f"[GlobalGraph] Cross-domain: +{stats['cross_domain_relations']} typed relations")
        except Exception as e:
            self._log(f"[GlobalGraph] Cross-domain engine ERROR: {e}")

        # ── 4. LLM Affinity ───────────────────────────────────────────────
        self._log("[GlobalGraph] ── Running LLM affinity pass ──")
        affinity_engine = LLMRelationEngine(self._graph, self._openai_key)
        stats["affinity_edges"] = affinity_engine.run(max_pairs=self._affinity_pairs)
        self._log(f"[GlobalGraph] Affinity: +{stats['affinity_edges']} cross-domain edges")

        # ── 5. Relation naming ────────────────────────────────────────────
        self._log("[GlobalGraph] ── Naming LLM_AFFINITY edges ──")
        namer = RelationNamer(self._graph, self._openai_key)
        stats["relations_named"] = namer.run()
        self._log(f"[GlobalGraph] Named {stats['relations_named']} affinity edges")

        # ── 6. Save ───────────────────────────────────────────────────────
        self._repo.save()
        self._log(f"[GlobalGraph] Saved. Graph: {self._repo.summary()}")

        return stats

    def summary(self) -> Dict:
        return self._repo.summary()
