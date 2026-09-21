from dotenv import load_dotenv
import os

load_dotenv()

KITE_API_KEY = os.getenv("KITE_API_KEY")
KITE_API_SECRET = os.getenv("KITE_API_SECRET")
KITE_ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")

DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")

DATABASE_URL = os.getenv("DATABASE_URL")\n\n# Live broker orders are opt-in; paper trading never depends on this flag.\nLIVE_TRADING_ENABLED = os.getenv("TRENDFORGE_LIVE_TRADING_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}