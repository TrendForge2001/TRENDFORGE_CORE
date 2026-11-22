"""Institutional data setup; everyday confluence appears in Stock Scanner."""

from webapp.institutional_workspace import institutional_workspace
from webapp.runtime import api_client
from webapp.ui import page_header

page_header(
    "Institutional Data",
    "Connect disclosures, import your private workbook and inspect source coverage.",
    kicker="DATA & CONNECTIONS",
)
institutional_workspace(api_client(timeout=45))
