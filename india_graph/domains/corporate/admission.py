from global_graph.domains.base_admission import BaseAdmissionPipeline
from india_graph.domains.corporate.ontology import DOMAIN


class IndiaCorporateAdmissionPipeline(BaseAdmissionPipeline):

    def __init__(self, repo, arbiter, schema, resolver):
        super().__init__(DOMAIN, repo, arbiter, schema, resolver)
