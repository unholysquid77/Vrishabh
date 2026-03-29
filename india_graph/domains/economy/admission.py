from global_graph.domains.base_admission import BaseAdmissionPipeline
from india_graph.domains.economy.ontology import DOMAIN


class EconomyAdmissionPipeline(BaseAdmissionPipeline):

    def __init__(self, repo, arbiter, schema, resolver):
        super().__init__(DOMAIN, repo, arbiter, schema, resolver)
