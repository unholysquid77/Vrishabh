from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
# ONTOLOGY TYPE CONSTANTS
# ──────────────────────────────────────────────

class EntityType:
    COMPANY          = "Company"
    EXECUTIVE        = "Executive"
    SECTOR           = "Sector"
    FILING           = "Filing"
    EVENT            = "Event"
    INSIDER_TRADE    = "InsiderTrade"
    NEWS_ITEM        = "NewsItem"
    MACRO_INDICATOR  = "MacroIndicator"


# ──────────────────────────────────────────────
# SOURCE PROVENANCE
# ──────────────────────────────────────────────

class SourceInfo(BaseModel):
    source_name: str
    source_url: Optional[str] = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)


# ──────────────────────────────────────────────
# CANONICAL ENTITY MODEL
# ──────────────────────────────────────────────

class FinanceEntity(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))

    ontology_type: str          # EntityType constant
    canonical_name: str
    aliases: List[str]          = Field(default_factory=list)
    description: Optional[str] = None

    # Ticker symbol if applicable (Company, InsiderTrade, NewsItem, etc.)
    ticker: Optional[str]       = None

    # Domain-specific payload — typed per ontology_type, stored as flat dict
    attributes: Dict[str, Any]  = Field(default_factory=dict)

    sources: List[SourceInfo]   = Field(default_factory=list)
    created_at: datetime        = Field(default_factory=datetime.utcnow)
    updated_at: datetime        = Field(default_factory=datetime.utcnow)

    # Confidence score 0–1 (aggregated from sources)
    confidence: float           = 1.0


# ──────────────────────────────────────────────
# TYPED CONSTRUCTORS
# Each returns a FinanceEntity with the correct ontology_type
# and attributes dict populated from typed kwargs.
# ──────────────────────────────────────────────

def make_company(
    ticker: str,
    name: str,
    sector: Optional[str]       = None,
    industry: Optional[str]     = None,
    exchange: str               = "NSE",
    market_cap: Optional[float] = None,   # in crores INR
    description: Optional[str]  = None,
    aliases: Optional[List[str]]= None,
    sources: Optional[List[SourceInfo]] = None,
) -> FinanceEntity:
    return FinanceEntity(
        ontology_type=EntityType.COMPANY,
        canonical_name=name,
        ticker=ticker.upper(),
        aliases=aliases or [],
        description=description,
        attributes={
            "sector":     sector,
            "industry":   industry,
            "exchange":   exchange,
            "market_cap": market_cap,
        },
        sources=sources or [],
    )


def make_executive(
    name: str,
    role: str,                          # "CEO", "CFO", "MD", "Director", etc.
    company_ticker: Optional[str] = None,
    aliases: Optional[List[str]]  = None,
    sources: Optional[List[SourceInfo]] = None,
) -> FinanceEntity:
    return FinanceEntity(
        ontology_type=EntityType.EXECUTIVE,
        canonical_name=name,
        ticker=company_ticker,
        aliases=aliases or [],
        attributes={"role": role, "company_ticker": company_ticker},
        sources=sources or [],
    )


def make_sector(
    name: str,
    aliases: Optional[List[str]] = None,
) -> FinanceEntity:
    return FinanceEntity(
        ontology_type=EntityType.SECTOR,
        canonical_name=name,
        aliases=aliases or [],
        attributes={},
    )


def make_filing(
    company_ticker: str,
    filing_type: str,                   # "quarterly", "annual", "BSE_disclosure"
    period: str,                        # e.g. "Q3FY25", "FY2024"
    summary: Optional[str]    = None,
    key_metrics: Optional[Dict[str, Any]] = None,
    filed_at: Optional[datetime] = None,
    sources: Optional[List[SourceInfo]] = None,
) -> FinanceEntity:
    return FinanceEntity(
        ontology_type=EntityType.FILING,
        canonical_name=f"{company_ticker} {filing_type} {period}",
        ticker=company_ticker,
        attributes={
            "filing_type": filing_type,
            "period":      period,
            "summary":     summary,
            "key_metrics": key_metrics or {},
            "filed_at":    filed_at.isoformat() if filed_at else None,
        },
        sources=sources or [],
    )


def make_event(
    company_ticker: str,
    event_type: str,                    # "earnings_beat", "earnings_miss", "M&A", "regulatory", "IPO", "management_change"
    title: str,
    description: Optional[str]    = None,
    event_date: Optional[datetime] = None,
    magnitude: Optional[float]    = None,  # severity/impact 0–1
    sources: Optional[List[SourceInfo]] = None,
) -> FinanceEntity:
    return FinanceEntity(
        ontology_type=EntityType.EVENT,
        canonical_name=title,
        ticker=company_ticker,
        attributes={
            "event_type":  event_type,
            "event_date":  event_date.isoformat() if event_date else None,
            "magnitude":   magnitude,
        },
        description=description,
        sources=sources or [],
    )


def make_insider_trade(
    company_ticker: str,
    trade_type: str,                    # "bulk_deal", "block_deal", "insider_buy", "insider_sell"
    trader_name: str,
    quantity: float,
    price: float,
    value_crores: Optional[float] = None,
    trade_date: Optional[datetime] = None,
    sources: Optional[List[SourceInfo]] = None,
) -> FinanceEntity:
    label = f"{trader_name} {trade_type} {company_ticker}"
    return FinanceEntity(
        ontology_type=EntityType.INSIDER_TRADE,
        canonical_name=label,
        ticker=company_ticker,
        attributes={
            "trade_type":    trade_type,
            "trader_name":   trader_name,
            "quantity":      quantity,
            "price":         price,
            "value_crores":  value_crores,
            "trade_date":    trade_date.isoformat() if trade_date else None,
        },
        sources=sources or [],
    )


def make_news_item(
    headline: str,
    source_name: str,
    url: Optional[str]             = None,
    published_at: Optional[datetime] = None,
    summary: Optional[str]         = None,
    sentiment_score: Optional[float] = None,  # -1 to +1
    tickers_mentioned: Optional[List[str]] = None,
    sources: Optional[List[SourceInfo]] = None,
) -> FinanceEntity:
    return FinanceEntity(
        ontology_type=EntityType.NEWS_ITEM,
        canonical_name=headline,
        attributes={
            "source_name":       source_name,
            "url":               url,
            "published_at":      published_at.isoformat() if published_at else None,
            "summary":           summary,
            "sentiment_score":   sentiment_score,
            "tickers_mentioned": tickers_mentioned or [],
        },
        sources=sources or [],
    )


def make_macro_indicator(
    name: str,                          # "Nifty50", "FII_net_flow", "DII_net_flow", "USD_INR"
    value: float,
    unit: Optional[str]              = None,
    as_of: Optional[datetime]        = None,
    sources: Optional[List[SourceInfo]] = None,
) -> FinanceEntity:
    return FinanceEntity(
        ontology_type=EntityType.MACRO_INDICATOR,
        canonical_name=name,
        attributes={
            "value":  value,
            "unit":   unit,
            "as_of":  as_of.isoformat() if as_of else None,
        },
        sources=sources or [],
    )
