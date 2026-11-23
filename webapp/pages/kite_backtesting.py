"""Scanner-selected stock research and encrypted strategy trade evidence."""

from webapp.runtime import admin_key_configured, api_client
from webapp.scanner_workflow_workspace import scanner_backtests
from webapp.ui import page_header

page_header(
    "Backtesting",
    "Strategy profitability and protected trade evidence.",
    kicker="HISTORICAL RESEARCH",
)
scanner_backtests(api_client(timeout=120), authorized=admin_key_configured())
