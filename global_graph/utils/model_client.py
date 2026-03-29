"""
ModelClient — thin OpenAI wrapper.
Provides generate_text() and generate_structured() (JSON schema mode).
"""

from __future__ import annotations
import json
from typing import Any, Dict, List, Optional, Type

from openai import OpenAI
from pydantic import BaseModel


class ModelClient:

    def __init__(self, api_key: str, default_model: str = "gpt-4o-mini"):
        self._client = OpenAI(api_key=api_key)
        self._model  = default_model

    # ── Plain text ────────────────────────────────────────────────────────

    def generate_text(
        self,
        prompt:       str,
        system:       str  = "",
        model:        Optional[str] = None,
        temperature:  float         = 0.3,
        max_tokens:   int           = 2048,
    ) -> str:
        messages: List[Dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        resp = self._client.chat.completions.create(
            model       = model or self._model,
            messages    = messages,
            temperature = temperature,
            max_tokens  = max_tokens,
        )
        return resp.choices[0].message.content or ""

    # ── Structured (JSON schema) ──────────────────────────────────────────

    def generate_structured(
        self,
        prompt:       str,
        system:       str,
        schema:       Dict[str, Any],
        model:        Optional[str] = None,
        temperature:  float         = 0.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Ask the model to return JSON matching `schema`.
        Uses response_format=json_object with schema instructions in the system prompt.
        """
        schema_str = json.dumps(schema, indent=2)
        full_system = (
            f"{system}\n\n"
            f"Respond ONLY with valid JSON matching this schema:\n{schema_str}"
        )
        messages = [
            {"role": "system", "content": full_system},
            {"role": "user",   "content": prompt},
        ]
        try:
            resp = self._client.chat.completions.create(
                model           = model or self._model,
                messages        = messages,
                temperature     = temperature,
                response_format = {"type": "json_object"},
            )
            raw = resp.choices[0].message.content or ""
            return json.loads(raw)
        except (json.JSONDecodeError, Exception):
            return None

    # ── Embeddings ────────────────────────────────────────────────────────

    def embed(self, texts: List[str], model: str = "text-embedding-3-small") -> List[List[float]]:
        resp = self._client.embeddings.create(model=model, input=texts)
        return [d.embedding for d in resp.data]
