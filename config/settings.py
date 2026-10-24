from dotenv import load_dotenv
import os

load_dotenv(encoding="utf-8-sig")

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

# Live broker orders are opt-in.
LIVE_TRADING_ENABLED = os.getenv(
    "TRENDFORGE_LIVE_TRADING_ENABLED",
    "false",
).strip().lower() in {"1", "true", "yes", "on"}

# Paper execution is separately opt-in and fail-closed. The environment kill
# switch defaults ON so a deployment never begins opening simulated positions
# merely because the feature flag was added.
PAPER_TRADING_ENABLED = os.getenv(
    "TRENDFORGE_PAPER_TRADING_ENABLED",
    "false",
).strip().lower() in {"1", "true", "yes", "on"}

PAPER_TRADING_KILL_SWITCH = os.getenv(
    "TRENDFORGE_PAPER_TRADING_KILL_SWITCH",
    "true",
).strip().lower() in {"1", "true", "yes", "on"}

PAPER_MONITOR_ENABLED = os.getenv(
    "TRENDFORGE_PAPER_MONITOR_ENABLED",
    "false",
).strip().lower() in {"1", "true", "yes", "on"}

PAPER_MONITOR_INTERVAL_SECONDS = os.getenv(
    "TRENDFORGE_PAPER_MONITOR_INTERVAL_SECONDS",
    "15",
)

PAPER_MONITOR_IDLE_SECONDS = os.getenv(
    "TRENDFORGE_PAPER_MONITOR_IDLE_SECONDS",
    "30",
)

PAPER_AUTO_ENTRY_ENABLED = os.getenv(
    "TRENDFORGE_PAPER_AUTO_ENTRY_ENABLED",
    "false",
).strip().lower() in {"1", "true", "yes", "on"}

PAPER_CAPITAL = os.getenv(
    "TRENDFORGE_PAPER_CAPITAL",
    "100000",
)

PAPER_RISK_PER_TRADE_PERCENT = os.getenv(
    "TRENDFORGE_PAPER_RISK_PER_TRADE_PERCENT",
    "1.0",
)

PAPER_MAX_DAILY_LOSS_PERCENT = os.getenv(
    "TRENDFORGE_PAPER_MAX_DAILY_LOSS_PERCENT",
    "3.0",
)

PAPER_MAX_OPEN_POSITIONS = os.getenv(
    "TRENDFORGE_PAPER_MAX_OPEN_POSITIONS",
    "5",
)

PAPER_MAX_CAPITAL_PER_TRADE_PERCENT = os.getenv(
    "TRENDFORGE_PAPER_MAX_CAPITAL_PER_TRADE_PERCENT",
    "20.0",
)

PAPER_MINIMUM_RR = os.getenv(
    "TRENDFORGE_PAPER_MINIMUM_RR",
    "2.0",
)

PAPER_AUTO_ENTRY_MIN_SCORE = os.getenv(
    "TRENDFORGE_PAPER_AUTO_ENTRY_MIN_SCORE",
    "90.0",
)

PAPER_AUTO_ENTRY_MIN_CONFIDENCE = os.getenv(
    "TRENDFORGE_PAPER_AUTO_ENTRY_MIN_CONFIDENCE",
    "60.0",
)

PAPER_AUTO_ENTRY_MAX_PER_SCAN = os.getenv(
    "TRENDFORGE_PAPER_AUTO_ENTRY_MAX_PER_SCAN",
    "1",
)

PAPER_AUTO_ENTRY_SIGNALS = os.getenv(
    "TRENDFORGE_PAPER_AUTO_ENTRY_SIGNALS",
    "STRONG BUY,BUY",
)
