"""Domain ingestors — fetch raw articles and convert to BaseRawModel."""

from global_graph.ingestors.newsdata_ingestor import NewsDataIngestor
from global_graph.ingestors.corporate_ingestor import CorporateIngestor
from global_graph.ingestors.geopolitics_ingestor import GeopoliticsIngestor
from global_graph.ingestors.climate_ingestor import ClimateIngestor
from global_graph.ingestors.technology_ingestor import TechnologyIngestor

__all__ = [
    "NewsDataIngestor",
    "CorporateIngestor",
    "GeopoliticsIngestor",
    "ClimateIngestor",
    "TechnologyIngestor",
]
