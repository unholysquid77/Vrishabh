"""
suvarn_client/_loader.py — mode detection for the TA client.

Prod mode (SUVARN_API_URL set)  : delegates to the live TA API endpoint.
Local mode (SUVARN_API_URL unset): uses the bundled ta_engine fallback.
"""

from __future__ import annotations
import os

# Mode detection
SUVARN_API_URL: str = os.getenv("SUVARN_API_URL", "")


def setup_suvarn_paths() -> None:
    """No-op — retained for import compatibility."""
    pass
