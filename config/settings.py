from dotenv import load_dotenv
import os

load_dotenv()

KITE_API_KEY = os.getenv("KITE_API_KEY")
KITE_API_SECRET = os.getenv("KITE_API_SECRET")
KITE_ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
DATABASE_URL = os.getenv("DATABASE_URL")

# Tijori enterprise/custom API configuration. The full provider-supplied URL
# template must contain {symbol}; TrendForge does not invent undocumented paths.
TIJORI_FUNDAMENTALS_URL_TEMPLATE = os.getenv("TIJORI_FUNDAMENTALS_URL_TEMPLATE")
TIJORI_API_KEY = os.getenv("TIJORI_API_KEY")
TIJORI_API_KEY_HEADER = os.getenv("TIJORI_API_KEY_HEADER", "Authorization")
TIJORI_API_KEY_PREFIX = os.getenv("TIJORI_API_KEY_PREFIX", "Bearer")
TIJORI_FIELD_MAP_JSON = os.getenv("TIJORI_FIELD_MAP_JSON")
TIJORI_TIMEOUT_SECONDS = os.getenv("TIJORI_TIMEOUT_SECONDS", "10")

# Screener.in has no API. These settings point to a user-generated premium CSV
# export (local file or user-controlled URL); no scraping/login automation occurs.
SCREENER_EXPORT_PATH = os.getenv("SCREENER_EXPORT_PATH")
SCREENER_EXPORT_URL = os.getenv("SCREENER_EXPORT_URL")
SCREENER_SYMBOL_COLUMN = os.getenv("SCREENER_SYMBOL_COLUMN")
SCREENER_FIELD_MAP_JSON = os.getenv("SCREENER_FIELD_MAP_JSON")
SCREENER_TIMEOUT_SECONDS = os.getenv("SCREENER_TIMEOUT_SECONDS", "10")

# Live broker orders are opt-in; paper trading never depends on this flag.
LIVE_TRADING_ENABLED = os.getenv("TRENDFORGE_LIVE_TRADING_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
