"""
suvarn_client — TA / sentiment / gateway facade.

Prod mode (SUVARN_API_URL set)  : delegates to the live API endpoint.
Local mode (SUVARN_API_URL unset): uses bundled ta_engine + sentiment fallbacks.

Public surface:
    SuvarnTAClient       — technical analysis (regime + signals + patterns)
    SuvarnBSNMClient     — business sentiment / news market scoring
    SuvarnGatewayClient  — veto / final-action decision engine

    TASignal             — TA result dataclass (re-exported for callers)
    BSNMResult           — BSNM result dataclass (re-exported for callers)
"""

from .ta_client      import SuvarnTAClient, TASignal          # noqa: F401
from .bsnm_client    import SuvarnBSNMClient, BSNMResult       # noqa: F401
from .gateway_client import SuvarnGatewayClient                # noqa: F401
