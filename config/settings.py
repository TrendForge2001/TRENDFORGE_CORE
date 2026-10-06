from dotenv import load_dotenv
import os

load_dotenv()

KITE_API_KEY = os.getenv("KITE_API_KEY")
KITE_API_SECRET = os.getenv("KITE_API_SECRET")
KITE_ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
DATABASE_URL = os.getenv("DATABASE_URL")

# Periodic fundamental-data import. TrendForge does not call Tijori/Screener APIs.
# Point this at a local/persistent CSV/XLSX/XLSM export when startup auto-import
# is desired; otherwise use the import CLI explicitly.
FUNDAMENTALS_IMPORT_PATH = os.getenv("FUNDAMENTALS_IMPORT_PATH")
FUNDAMENTALS_IMPORT_SOURCE = os.getenv("FUNDAMENTALS_IMPORT_SOURCE", "manual_file")
FUNDAMENTALS_SYMBOL_COLUMN = os.getenv("FUNDAMENTALS_SYMBOL_COLUMN")
FUNDAMENTALS_FIELD_MAP_JSON = os.getenv("FUNDAMENTALS_FIELD_MAP_JSON")
FUNDAMENTALS_SHEET_NAME = os.getenv("FUNDAMENTALS_SHEET_NAME", "0")
FUNDAMENTALS_AS_OF = os.getenv("FUNDAMENTALS_AS_OF")
FUNDAMENTALS_MAX_AGE_DAYS = os.getenv("FUNDAMENTALS_MAX_AGE_DAYS", "200")

# Live broker orders are opt-in; paper trading never depends on this flag.
LIVE_TRADING_ENABLED = os.getenv("TRENDFORGE_LIVE_TRADING_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
