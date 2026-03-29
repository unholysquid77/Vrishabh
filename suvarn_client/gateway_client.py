"""
suvarn_client/gateway_client.py — Gateway / veto engine.

Gateway logic: TA is supreme.  Business sentiment can veto a BUY or
upgrade a HOLD.  Social sentiment gives a small score boost only.

Prod mode (SUVARN_API_URL set): POST to API /gateway endpoint.
Local mode                     : uses built-in fallback logic.
"""

from __future__ import annotations

from typing import Optional

from ._loader import SUVARN_API_URL


# Veto thresholds
_BHV  = -0.40   # hard business veto threshold
_BSP  = +0.35   # strong positive upgrade threshold
_SSB  = +0.15   # social soft boost weight


def _fallback_evaluate_veto(ticker, ta_signal, business, social):
    ta_score  = ta_signal["score"]
    threshold = ta_signal["threshold"]
    ta_action = ta_signal["suggested_action"]

    b = business.get("sentiment", 0)
    s = social.get("sentiment", 0)

    ta_boosted = ta_score + s * _SSB
    allow_buy  = True
    force_sell = False
    reason     = None

    if ta_action in ("Buy", "BUY") and b <= _BHV:
        allow_buy = False
        reason    = f"Hard Business Veto (b={b:.3f})"

    if ta_action in ("Hold", "HOLD") and b >= _BSP:
        allow_buy = True
        reason    = f"Business Positive Upgrade (b={b:.3f})"

    if ta_action in ("Buy", "BUY"):
        final_action = "Buy" if allow_buy else "Hold"
    elif ta_action in ("Sell", "SELL"):
        final_action = "Sell"
    else:
        final_action = "Buy" if b >= _BSP else "Hold"

    return {
        "ticker":             ticker,
        "final_action":       final_action,
        "allow_buy":          allow_buy,
        "force_sell":         force_sell,
        "reason":             reason,
        "ta_score_original":  ta_score,
        "ta_score_boosted":   ta_boosted,
        "business":           b,
        "social":             s,
        "confidence":         abs(ta_score / max(threshold, 1e-6)),
    }


class SuvarnGatewayClient:
    """
    Gateway veto / final-action engine.

    Prod mode (SUVARN_API_URL set): POST to /gateway endpoint.
    Local mode                     : runs built-in fallback logic.
    """

    def evaluate(
        self,
        ticker:    str,
        ta_signal: dict,
        business:  Optional[dict] = None,
        social:    Optional[dict] = None,
    ) -> dict:
        """
        Apply the gateway veto logic.

        ta_signal must contain: {"score", "threshold", "suggested_action"}.
        business / social: {"sentiment": float -1..+1} dicts (optional).
        Returns: {"final_action": "Buy"|"Sell"|"Hold", "reason": ..., ...}
        """
        if SUVARN_API_URL:
            # TODO: POST to SUVARN_API_URL + "/gateway"
            pass
        return _fallback_evaluate_veto(
            ticker,
            ta_signal,
            business or {},
            social   or {},
        )

    def batch_evaluate(self, signals: list, business_json: dict, social_json: dict) -> dict:
        """
        Convenience: evaluate multiple signals at once.
        signals  : list of ta_signal dicts (each must have "ticker").
        business_json / social_json : {"companies": {SYM: {"sentiment": ...}}}
        """
        from datetime import datetime
        out = {}
        for sig in signals:
            ticker = sig["ticker"]
            clean  = ticker.replace(".NS", "").replace(".BO", "")
            biz    = (business_json.get("companies") or {}).get(clean, {})
            soc    = (social_json.get("companies")   or {}).get(clean, {})
            out[ticker] = self.evaluate(ticker, sig, biz, soc)
        return {"timestamp": datetime.utcnow().isoformat(), "signals": out}
