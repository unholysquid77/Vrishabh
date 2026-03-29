"""
Global Graph — Paqshi-style multi-domain intelligence graph.
Domains: corporate, geopolitics, climate, technology.
"""

from global_graph.core.base_entity import BaseEntity
from global_graph.core.base_relation import BaseRelation
from global_graph.graphs.ontology_graph import OntologyGraph
from global_graph.graphs.graph_repository import GlobalGraphRepository

__all__ = [
    "BaseEntity",
    "BaseRelation",
    "OntologyGraph",
    "GlobalGraphRepository",
]
