"""
India Graph — Paqshi-style ontology for Indian business, finance, policy, and economy.
Reuses global_graph infrastructure (OntologyGraph, SchemaRegistry, EntityResolver, etc.)
India-specific: entity types, arbiters, admission pipelines, ingestors.
"""

from global_graph.graphs.ontology_graph import OntologyGraph
from global_graph.graphs.graph_repository import GlobalGraphRepository

__all__ = ["OntologyGraph", "GlobalGraphRepository"]
