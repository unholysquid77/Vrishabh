"""
Opportunity Radar — Vrishabh's signal-finder.

Aggregates signals from:
  - TA engine (score, regime, patterns)
  - BSNM (news sentiment)
  - Graph events (filings, insider trades, corporate events)

Surfaces high-conviction alerts. NOT a summariser — a signal-finder.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from graph import GraphRepository
from graph.entities import EntityType
from suvarn_client import SuvarnTAClient as TAEngine, TASignal, SuvarnBSNMClient as BSNMEngine, BSNMResult


# ──────────────────────────────────────────────
# ALERT MODEL
# ──────────────────────────────────────────────

class Alert:
    def __init__(
        self,
        ticker:          str,
        alert_type:      str,
        title:           str,
        body:            str,
        strength:        float,        # 0–1
        direction:       str,          # "bullish" | "bearish" | "neutral"
        suggested_action: str,         # "BUY" | "SELL" | "WATCH" | "HOLD"
        evidence:        List[str],    # human-readable evidence list
        generated_at:    Optional[datetime] = None,
    ):
        self.ticker           = ticker
        self.alert_type       = alert_type
        self.title            = title
        self.body             = body
        self.strength         = strength
        self.direction        = direction
        self.suggested_action = suggested_action
        self.evidence         = evidence
        self.generated_at     = generated_at or datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "ticker":           self.ticker,
            "alert_type":       self.alert_type,
            "title":            self.title,
            "body":             self.body,
            "strength":         round(self.strength, 3),
            "direction":        self.direction,
            "suggested_action": self.suggested_action,
            "evidence":         self.evidence,
            "generated_at":     self.generated_at.isoformat(),
        }


# ──────────────────────────────────────────────
# OPPORTUNITY RADAR
# ──────────────────────────────────────────────

class OpportunityRadar:
    def __init__(
        self,
        repo:   GraphRepository,
        ta:     TAEngine,
        bsnm:   BSNMEngine,
    ):
        self.repo  = repo
        self.graph = repo.graph
        self.ta    = ta
        self.bsnm  = bsnm

    def scan(self, tickers: List[str]) -> List[Alert]:
        """
        Full radar scan for given tickers.
        Returns alerts sorted by strength descending.
        """
        # 1. TA signals (concurrent)
        ta_signals = self.ta.analyse_many(tickers)

        # 2. BSNM sentiment (concurrent, only top candidates)
        top_tickers = sorted(
            ta_signals.keys(),
            key=lambda t: abs(ta_signals[t].score),
            reverse=True,
        )[:30]
        bsnm_results = self.bsnm.analyse_many(top_tickers)

        # 3. Generate alerts
        all_alerts: List[Alert] = []

        for ticker in tickers:
            ta_sig  = ta_signals.get(ticker)
            bsnm_r  = bsnm_results.get(ticker)

            if ta_sig:
                all_alerts.extend(self._ta_alerts(ta_sig, bsnm_r))
            if bsnm_r:
                all_alerts.extend(self._news_alerts(ticker, bsnm_r, ta_sig))

            all_alerts.extend(self._graph_alerts(ticker, ta_sig))

        # 4. Sort by strength, then dedup by (ticker, title) — duplicate EVENT
        #    nodes from repeated news pipeline runs produce identical alerts.
        all_alerts.sort(key=lambda a: a.strength, reverse=True)
        seen: set = set()
        deduped: List[Alert] = []
        for a in all_alerts:
            key = (a.ticker, a.title)
            if key not in seen:
                seen.add(key)
                deduped.append(a)
        return deduped

    # ──────────────────────────────────────────
    # TA-DERIVED ALERTS
    # ──────────────────────────────────────────

    def _ta_alerts(self, sig: TASignal, bsnm: Optional[BSNMResult]) -> List[Alert]:
        alerts = []
        business_score = bsnm.score if bsnm else 0.0

        # ── Strong TA + positive business → high-conviction BUY ──
        if sig.suggested_action == "BUY" and business_score > 0.25:
            combined = min((sig.confidence + business_score) / 2 + 0.1, 1.0)
            alerts.append(Alert(
                ticker           = sig.ticker,
                alert_type       = "TA_BSNM_CONFLUENCE",
                title            = f"{sig.ticker}: Technical + News Confluence",
                body             = (
                    f"Strong TA buy signal (score {sig.score:.2f}, regime: {sig.regime}) "
                    f"confirmed by positive news sentiment ({business_score:+.2f}). "
                    f"{bsnm.headline_summary if bsnm else ''}"
                ),
                strength         = combined,
                direction        = "bullish",
                suggested_action = "BUY",
                evidence         = [
                    f"TA score: {sig.score:.2f} vs threshold {sig.threshold:.2f}",
                    f"Regime: {sig.regime} — {sig.regime_desc}",
                    f"Business sentiment: {business_score:+.2f}",
                ] + ([f"Pattern: {p['name']} — {p['explanation']}" for p in sig.patterns[:2]]),
            ))

        # ── Bearish TA + negative news → sell/exit alert ─────────
        elif sig.suggested_action == "SELL" and business_score < -0.25:
            strength = min((sig.confidence + abs(business_score)) / 2, 1.0)
            alerts.append(Alert(
                ticker           = sig.ticker,
                alert_type       = "TA_BSNM_BEAR_CONFLUENCE",
                title            = f"{sig.ticker}: Bearish Signal — Consider Exiting",
                body             = (
                    f"TA sell signal (score {sig.score:.2f}) combined with negative news ({business_score:+.2f}). "
                    f"{bsnm.headline_summary if bsnm else ''}"
                ),
                strength         = strength,
                direction        = "bearish",
                suggested_action = "SELL",
                evidence         = [
                    f"TA score: {sig.score:.2f} below zero",
                    f"Business sentiment: {business_score:+.2f}",
                ],
            ))

        # ── Significant chart patterns ────────────────────────────
        for pattern in sig.patterns:
            if pattern.get("strength", 0) >= 0.75:
                direction  = pattern["direction"]
                action     = "BUY" if direction == "bullish" else ("SELL" if direction == "bearish" else "WATCH")
                alerts.append(Alert(
                    ticker           = sig.ticker,
                    alert_type       = "CHART_PATTERN",
                    title            = f"{sig.ticker}: {pattern['name']} Detected",
                    body             = pattern["explanation"],
                    strength         = float(pattern["strength"]) * max(sig.confidence, 0.65),
                    direction        = direction,
                    suggested_action = action,
                    evidence         = [
                        pattern["explanation"],
                        f"Regime: {sig.regime}",
                        f"Last close: ₹{sig.last_close:.2f}",
                    ],
                ))

        # ── Regime breakout alert ─────────────────────────────────
        if sig.regime in ("BREAKOUT", "WHALE"):
            alerts.append(Alert(
                ticker           = sig.ticker,
                alert_type       = "REGIME_ALERT",
                title            = f"{sig.ticker}: {sig.regime} Regime Detected",
                body             = sig.regime_desc,
                strength         = 0.7 if sig.regime == "WHALE" else 0.65,
                direction        = "bullish" if sig.score > 0 else "bearish",
                suggested_action = "WATCH",
                evidence         = [sig.regime_desc, f"TA score: {sig.score:.2f}"],
            ))

        return alerts

    # ──────────────────────────────────────────
    # NEWS-DERIVED ALERTS
    # ──────────────────────────────────────────

    def _news_alerts(
        self, ticker: str, bsnm: BSNMResult, ta: Optional[TASignal]
    ) -> List[Alert]:
        alerts = []

        # Strong standalone news signal (when TA is neutral/absent)
        if abs(bsnm.score) >= 0.5:
            direction = "bullish" if bsnm.score > 0 else "bearish"
            action    = "WATCH" if ta and ta.suggested_action == "HOLD" else (
                "BUY" if direction == "bullish" else "SELL"
            )
            alerts.append(Alert(
                ticker           = ticker,
                alert_type       = "STRONG_NEWS",
                title            = f"{ticker}: Strong {'Positive' if bsnm.score > 0 else 'Negative'} News Flow",
                body             = bsnm.headline_summary,
                strength         = min(abs(bsnm.score), 1.0) * 0.7,
                direction        = direction,
                suggested_action = action,
                evidence         = bsnm.top_headlines[:3] + [
                    f"News sentiment score: {bsnm.score:+.2f}",
                    f"Articles analysed: {bsnm.articles_found}",
                ],
            ))

        return alerts

    # ──────────────────────────────────────────
    # GRAPH-DERIVED ALERTS (events, insider trades)
    # ──────────────────────────────────────────

    def _graph_alerts(self, ticker: str, ta: Optional[TASignal]) -> List[Alert]:
        alerts = []
        company = self.graph.get_company_node(ticker)
        if not company:
            return []

        # Look for recent InsiderTrade entities linked to this company
        insider_trades = [
            self.graph.get_node(rel.to_node_id)
            for rel in self.graph.get_relations_from(company.id)
            if self.graph.get_node(rel.to_node_id)
            and self.graph.get_node(rel.to_node_id).ontology_type == EntityType.INSIDER_TRADE
        ]

        for trade_node in insider_trades:
            attrs      = trade_node.attributes
            trade_type = attrs.get("trade_type", "")
            trader     = attrs.get("trader_name", "Unknown")
            value_cr   = attrs.get("value_crores")
            is_buy     = "buy" in trade_type.lower() or "bulk" in trade_type.lower()

            if value_cr and float(value_cr) >= 10:   # only significant trades
                direction = "bullish" if is_buy else "bearish"
                alerts.append(Alert(
                    ticker           = ticker,
                    alert_type       = "INSIDER_TRADE",
                    title            = f"{ticker}: Significant {trade_type.replace('_', ' ').title()}",
                    body             = (
                        f"{trader} {'bought' if is_buy else 'sold'} ₹{value_cr:.1f} Cr worth of {ticker} "
                        f"({attrs.get('quantity', '?'):.0f} shares @ ₹{attrs.get('price', '?'):.2f})"
                        if isinstance(attrs.get("quantity"), (int, float)) and isinstance(attrs.get("price"), (int, float))
                        else f"{trader} executed a significant {trade_type.replace('_', ' ')}."
                    ),
                    strength         = min(float(value_cr) / 100, 0.9),  # normalise by ₹100Cr
                    direction        = direction,
                    suggested_action = "WATCH",
                    evidence         = [
                        f"Trade type: {trade_type}",
                        f"Trader: {trader}",
                        f"Value: ₹{value_cr:.1f} Cr",
                    ],
                ))

        # Recent high-magnitude Events
        event_nodes = [
            self.graph.get_node(rel.to_node_id)
            for rel in self.graph.get_relations_from(company.id)
            if self.graph.get_node(rel.to_node_id)
            and self.graph.get_node(rel.to_node_id).ontology_type == EntityType.EVENT
        ]

        for ev in event_nodes:
            magnitude  = float(ev.attributes.get("magnitude", 0))
            event_type = ev.attributes.get("event_type", "other")
            if magnitude >= 0.6:
                direction = (
                    "bullish" if event_type in ("earnings_beat", "partnership", "product_launch", "debt_upgrade")
                    else "bearish" if event_type in ("earnings_miss", "regulatory", "debt_downgrade")
                    else "neutral"
                )
                alerts.append(Alert(
                    ticker           = ticker,
                    alert_type       = "CORPORATE_EVENT",
                    title            = f"{ticker}: {ev.canonical_name}",
                    body             = ev.description or ev.canonical_name,
                    strength         = magnitude * 0.8,
                    direction        = direction,
                    suggested_action = "WATCH",
                    evidence         = [
                        f"Event type: {event_type}",
                        f"Magnitude: {magnitude:.2f}",
                    ],
                ))

        return alerts
