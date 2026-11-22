"""Visual company research; fundamental strategy rules remain owner-defined."""

from webapp.runtime import admin_key_configured, api_client
from webapp.stock_report_workspace import render_stock_report_workspace
from webapp.ui import page_header

page_header(
    "Fundamental insights",
    "Company facts, shareholding and financial trends with dated sources.",
    kicker="STOCK RESEARCH",
)
if admin_key_configured():
    render_stock_report_workspace(api_client(timeout=120), key="fundamental_report")
