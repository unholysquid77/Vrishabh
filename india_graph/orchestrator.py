"""
IndiaGraphOrchestrator — full pipeline driver for the India intelligence graph.

Pipeline per run:
  1. Ingest articles from all 4 India domain ingestors
  2. Run domain arbiters + admission pipelines
  3. GraphDedup pass
  4. Cross-domain typed relation engine
  5. LLMRelationEngine cross-domain affinity pass
  6. RelationNamer pass
  7. Save graph to disk
"""

from __future__ import annotations
from datetime import datetime
from typing import Callable, Dict, Optional

from global_graph.graphs.ontology_graph import OntologyGraph
from global_graph.graphs.graph_repository import GlobalGraphRepository
from global_graph.graphs.schema_registry import SchemaRegistry
from global_graph.graphs.graph_dedup import GraphDedup
from global_graph.graphs.llm_relation_engine import LLMRelationEngine
from global_graph.graphs.relation_namer import RelationNamer
from global_graph.graphs.cross_domain_engine import CrossDomainEngine, INDIA_CROSS_DOMAIN_SCHEMAS
from global_graph.utils.model_client import ModelClient
from global_graph.utils.entity_resolver import EntityResolver

from india_graph.domains.finance.ontology import FINANCE_SCHEMA, FINANCE_RELATIONS
from india_graph.domains.finance.arbiter import FinanceArbiter
from india_graph.domains.finance.admission import FinanceAdmissionPipeline

from india_graph.domains.policy.ontology import POLICY_SCHEMA, POLICY_RELATIONS
from india_graph.domains.policy.arbiter import PolicyArbiter
from india_graph.domains.policy.admission import PolicyAdmissionPipeline

from india_graph.domains.economy.ontology import ECONOMY_SCHEMA, ECONOMY_RELATIONS
from india_graph.domains.economy.arbiter import EconomyArbiter
from india_graph.domains.economy.admission import EconomyAdmissionPipeline

from india_graph.domains.corporate.ontology import INDIA_CORPORATE_SCHEMA, INDIA_CORPORATE_RELATIONS
from india_graph.domains.corporate.arbiter import IndiaCorporateArbiter
from india_graph.domains.corporate.admission import IndiaCorporateAdmissionPipeline

from india_graph.ingestors.finance_ingestor import IndiaFinanceIngestor
from india_graph.ingestors.policy_ingestor import IndiaPolicyIngestor
from india_graph.ingestors.economy_ingestor import IndiaEconomyIngestor
from india_graph.ingestors.corporate_ingestor import IndiaCorporateIngestor

LOG = Callable[[str], None]

# Domain color for vis.js (amber — distinct from global graph)
INDIA_DOMAIN_COLORS = {
    "india_finance":   "#F59E0B",
    "india_policy":    "#06B6D4",
    "india_economy":   "#10B981",
    "india_corporate": "#F97316",
}


class IndiaGraphOrchestrator:

    def __init__(
        self,
        openai_key:    str,
        newsdata_key:  str,
        graph_file:    str,
        log_callback:  Optional[LOG] = None,
        max_articles_per_domain: int = 40,
        affinity_pairs: int          = 100,
    ):
        self._openai_key   = openai_key
        self._newsdata_key = newsdata_key
        self._graph_file   = graph_file
        self._log          = log_callback or print
        self._max_articles = max_articles_per_domain
        self._affinity_pairs = affinity_pairs

        # ── Core objects ──────────────────────────────────────────────────
        self._graph    = OntologyGraph()
        self._schema   = self._build_schema()
        self._repo     = GlobalGraphRepository(
            graph      = self._graph,
            file_path  = self._graph_file,
            schema     = self._schema,
            openai_key = self._openai_key,
        )
        # Patch domain colors into the repository's vis export
        self._repo._DOMAIN_COLORS = INDIA_DOMAIN_COLORS

        self._indexer  = self._repo._indexer
        self._resolver = EntityResolver(self._graph, self._indexer)
        self._model    = ModelClient(self._openai_key)

        # ── Domain pipelines ──────────────────────────────────────────────
        self._fin_pipeline  = FinanceAdmissionPipeline(
            self._repo, FinanceArbiter(self._model), self._schema, self._resolver
        )
        self._pol_pipeline  = PolicyAdmissionPipeline(
            self._repo, PolicyArbiter(self._model), self._schema, self._resolver
        )
        self._eco_pipeline  = EconomyAdmissionPipeline(
            self._repo, EconomyArbiter(self._model), self._schema, self._resolver
        )
        self._corp_pipeline = IndiaCorporateAdmissionPipeline(
            self._repo, IndiaCorporateArbiter(self._model), self._schema, self._resolver
        )

        # ── Ingestors ─────────────────────────────────────────────────────
        self._fin_ingestor  = IndiaFinanceIngestor(self._newsdata_key)
        self._pol_ingestor  = IndiaPolicyIngestor(self._newsdata_key)
        self._eco_ingestor  = IndiaEconomyIngestor(self._newsdata_key)
        self._corp_ingestor = IndiaCorporateIngestor(self._newsdata_key)

    # ── Schema ────────────────────────────────────────────────────────────

    def _build_schema(self) -> SchemaRegistry:
        schema = SchemaRegistry()
        schema.register_domain("india_finance",   FINANCE_SCHEMA,          FINANCE_RELATIONS)
        schema.register_domain("india_policy",    POLICY_SCHEMA,           POLICY_RELATIONS)
        schema.register_domain("india_economy",   ECONOMY_SCHEMA,          ECONOMY_RELATIONS)
        schema.register_domain("india_corporate", INDIA_CORPORATE_SCHEMA,  INDIA_CORPORATE_RELATIONS)
        return schema

    # ── Public API ────────────────────────────────────────────────────────

    @property
    def repo(self) -> GlobalGraphRepository:
        return self._repo

    @property
    def graph(self) -> OntologyGraph:
        return self._graph

    def load(self):
        self._repo.load()
        self._log(f"[IndiaGraph] Loaded: {self._repo.summary()}")

    def run(self) -> Dict[str, int]:
        """Full ingestion + enrichment pipeline. Returns stats."""
        from datetime import datetime as _dt
        run_ts = _dt.utcnow().isoformat()
        stats: Dict[str, int] = {
            "finance_entities": 0,   "finance_relations": 0,
            "policy_entities": 0,    "policy_relations": 0,
            "economy_entities": 0,   "economy_relations": 0,
            "corporate_entities": 0, "corporate_relations": 0,
            "dedup_merges": 0,
            "affinity_edges": 0,
            "cross_domain_relations": 0,
            "relations_named": 0,
        }

        node_before = len(self._graph.nodes)
        rel_before  = len(self._graph.relations)
        self._log(f"[IndiaGraph] Starting run at {run_ts} — graph has {node_before} nodes, {rel_before} relations")

        # ── 1. Ingest + Admit ─────────────────────────────────────────────
        for domain, ingestor, pipeline, prefix in [
            ("india_finance",   self._fin_ingestor,  self._fin_pipeline,  "finance"),
            ("india_policy",    self._pol_ingestor,  self._pol_pipeline,  "policy"),
            ("india_economy",   self._eco_ingestor,  self._eco_pipeline,  "economy"),
            ("india_corporate", self._corp_ingestor, self._corp_pipeline, "corporate"),
        ]:
            self._log(f"[IndiaGraph] ── Ingesting {domain} ──")
            try:
                articles = ingestor.fetch(max_articles=self._max_articles)
                self._log(f"[IndiaGraph] {domain}: {len(articles)} raw items fetched")
                for i, raw in enumerate(articles, 1):
                    result = pipeline.ingest(raw)
                    e = result["entities"]
                    r = result["relations"]
                    stats[f"{prefix}_entities"]  += e
                    stats[f"{prefix}_relations"] += r
                    if e > 0:
                        self._log(f"[IndiaGraph] {domain} [{i}/{len(articles)}] admitted {e}e {r}r — '{(raw.title or raw.text[:60]).strip()}'")
                self._log(
                    f"[IndiaGraph] {domain} done: "
                    f"+{stats[f'{prefix}_entities']} entities, "
                    f"+{stats[f'{prefix}_relations']} relations"
                )
            except Exception as e:
                self._log(f"[IndiaGraph] {domain} ERROR: {e}")

        total_new_nodes = len(self._graph.nodes) - node_before
        total_new_rels  = len(self._graph.relations) - rel_before
        self._log(f"[IndiaGraph] Ingestion complete: +{total_new_nodes} nodes, +{total_new_rels} relations")

        # ── 2. Dedup ──────────────────────────────────────────────────────
        self._log("[IndiaGraph] ── Running dedup pass ──")
        dedup = GraphDedup(self._graph, self._indexer)
        stats["dedup_merges"] = dedup.run()
        self._log(f"[IndiaGraph] Dedup merged {stats['dedup_merges']} nodes → {len(self._graph.nodes)} total")

        # ── 3. Cross-domain typed relations ───────────────────────────────
        self._log("[IndiaGraph] ── Running cross-domain typed relation engine ──")
        try:
            cross_engine = CrossDomainEngine(
                graph      = self._graph,
                openai_key = self._openai_key,
                schemas    = INDIA_CROSS_DOMAIN_SCHEMAS,
            )
            stats["cross_domain_relations"] = cross_engine.run(max_pairs_per_schema=25)
            self._log(f"[IndiaGraph] Cross-domain: +{stats['cross_domain_relations']} typed relations")
        except Exception as e:
            self._log(f"[IndiaGraph] Cross-domain engine ERROR: {e}")

        # ── 4. LLM Affinity ───────────────────────────────────────────────
        self._log("[IndiaGraph] ── Running LLM affinity pass ──")
        affinity_engine = LLMRelationEngine(self._graph, self._openai_key)
        stats["affinity_edges"] = affinity_engine.run(max_pairs=self._affinity_pairs)
        self._log(f"[IndiaGraph] Affinity: +{stats['affinity_edges']} cross-domain edges")

        # ── 5. Relation naming ────────────────────────────────────────────
        self._log("[IndiaGraph] ── Naming LLM_AFFINITY edges ──")
        namer = RelationNamer(self._graph, self._openai_key)
        stats["relations_named"] = namer.run()
        self._log(f"[IndiaGraph] Named {stats['relations_named']} affinity edges")

        # ── 6. Save ───────────────────────────────────────────────────────
        self._repo.save()
        self._log(f"[IndiaGraph] Saved. Graph: {self._repo.summary()}")

        return stats

    def summary(self) -> Dict:
        return self._repo.summary()
