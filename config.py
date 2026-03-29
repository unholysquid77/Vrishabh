import os
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# API KEYS
# ──────────────────────────────────────────────
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY", "")
MARKETAUX_API_KEY = os.getenv("MARKETAUX_API_KEY", "")
NEWSAPI_KEY       = os.getenv("NEWSAPI_KEY", "")
NEWSDATA_API_KEY  = os.getenv("NEWSDATA_API_KEY", "")
ANGEL_API_KEY     = os.getenv("ANGEL_API_KEY", "")
ANGEL_CLIENT_ID   = os.getenv("ANGEL_CLIENT_ID", "")
ANGEL_PASSWORD    = os.getenv("ANGEL_PASSWORD", "")
ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")
INDIANAPI_KEY     = os.getenv("INDIANAPI_KEY", "")

# ACLED (Armed Conflict Location & Event Data) — optional, free registration at acleddata.com
ACLED_EMAIL    = os.getenv("ACLED_EMAIL", "")
ACLED_PASSWORD = os.getenv("ACLED_PASSWORD", "")

# ──────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────
GRAPH_FILE        = os.path.join(os.path.dirname(__file__), "data", "graph.json")
GLOBAL_GRAPH_FILE = os.path.join(os.path.dirname(__file__), "data", "global_graph.json")
INDIA_GRAPH_FILE  = os.path.join(os.path.dirname(__file__), "data", "india_graph.json")

# ──────────────────────────────────────────────
# WATCHLIST  —  Nifty 500 core + user-extended
# ──────────────────────────────────────────────
NIFTY_500_TICKERS = [
    # Nifty 50 (core)
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "SBIN", "BHARTIARTL", "ITC", "KOTAKBANK",
    "LT", "BAJFINANCE", "HCLTECH", "ASIANPAINT", "AXISBANK",
    "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO", "WIPRO",
    "NESTLEIND", "BAJAJFINSV", "POWERGRID", "NTPC", "TECHM",
    "ONGC", "TATASTEEL", "TMCV", "ADANIENT", "ADANIGREEN",
    "COALINDIA", "JSWSTEEL", "DRREDDY", "DIVISLAB", "CIPLA",
    "HINDALCO", "VEDL", "BPCL", "GRASIM", "EICHERMOT",
    "BRITANNIA", "HEROMOTOCO", "BAJAJ-AUTO", "TATACONSUM", "APOLLOHOSP",
    "LTIM", "INDUSINDBK", "M&M", "UPL", "SHREECEM",
    # Additional Nifty 500 coverage
    "IRFC", "RECLTD", "PFC", "CANBK", "BANKBARODA",
    "SBILIFE", "HDFCLIFE", "ICICIGI", "LICI",
    "ZOMATO", "NYKAA", "PAYTM", "POLICYBZR",
    "TRENT", "DMART", "ABFRL", "PAGEIND",
    "PIDILITIND", "BERGEPAINT", "AKZOINDIA",
    "HAVELLS", "VOLTAS", "WHIRLPOOL", "BLUESTARCO",
    "MCDOWELL-N", "RADICO",
    "GODREJCP", "MARICO", "DABUR", "EMAMILTD",
    "LUPIN", "AUROPHARMA", "TORNTPHARM", "ALKEM",
    "BALKRISIND", "CEATLTD", "APOLLOTYRE",
    "SIEMENS", "ABB", "BHEL", "THERMAX",
    "PIIND", "UBL", "MPHASIS", "COFORGE",
    "PERSISTENT", "LTTS", "KPITTECH",
    "TATAPOWER", "ADANIPORTS", "ADANIENSOL",
    "NAUKRI", "JUSTDIAL", "INDIGOPNTS",
    "IDFCFIRSTB", "FEDERALBNK", "RBLBANK",
    "CHOLAFIN", "MUTHOOTFIN", "MANAPPURAM",
    "HAL", "BEL", "BHEL", "COCHINSHIP",
    "ASTRAL", "SUPREMEIND", "FINOLEXCAB",
    "CUMMINSIND", "GRINDWELL",
    "GMRAIRPORT", "IRB",
    "IRCTC", "CONCOR",
]

# Remove duplicates while preserving order
seen = set()
NIFTY_500_TICKERS = [t for t in NIFTY_500_TICKERS if not (t in seen or seen.add(t))]

# yfinance appends .NS for NSE stocks; index tickers like ^NSEI already have no suffix
def to_yf_ticker(ticker: str) -> str:
    if ticker.startswith("^"):          # index ticker (^NSEI, ^BSESN, etc.)
        return ticker
    if ticker.endswith("=X"):           # forex pair (USDINR=X, EURUSD=X, etc.)
        return ticker
    if ticker.endswith(".NS") or ticker.endswith(".BO"):
        return ticker
    return ticker + ".NS"

# ──────────────────────────────────────────────
# TA ENGINE
# ──────────────────────────────────────────────
TA_LOOKBACK_BARS    = 300   # number of daily bars to fetch for TA
TA_SCORE_BUY_THRESHOLD  = 0.40
TA_SCORE_SELL_THRESHOLD = -0.40

# ──────────────────────────────────────────────
# LLM MODELS
# ──────────────────────────────────────────────
LLM_MODEL_MAIN      = "gpt-4o"
LLM_MODEL_FAST      = "gpt-4o-mini"   # for bulk sentiment calls
LLM_EMBED_MODEL     = "text-embedding-3-small"

# ──────────────────────────────────────────────
# NEWS PIPELINE
# ──────────────────────────────────────────────
NEWS_CACHE_TTL_HOURS = 12
NEWS_MAX_ARTICLES    = 10   # per ticker per source
