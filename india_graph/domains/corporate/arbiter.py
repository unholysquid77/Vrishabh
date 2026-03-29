from __future__ import annotations
from typing import Any, Dict, Optional

from global_graph.domains.base_raw_model import BaseRawModel
from india_graph.domains.corporate.ontology import ARBITER_SYSTEM_PROMPT, ARBITER_OUTPUT_SCHEMA
from global_graph.utils.model_client import ModelClient


class IndiaCorporateArbiter:

    def __init__(self, model_client: ModelClient):
        self._client = model_client

    def extract(self, raw: BaseRawModel) -> Optional[Dict[str, Any]]:
        prompt = (
            f"Article title: {raw.title or 'N/A'}\n"
            f"Source: {raw.source_url}\n\n"
            f"{raw.text[:3000]}"
        )
        result = self._client.generate_structured(
            prompt = prompt,
            system = ARBITER_SYSTEM_PROMPT,
            schema = ARBITER_OUTPUT_SCHEMA,
            model  = "gpt-4o-mini",
        )
        if not result or "entities" not in result:
            return None
        if not isinstance(result.get("entities"), list):
            result["entities"] = []
        if not isinstance(result.get("relations"), list):
            result["relations"] = []
        return result
