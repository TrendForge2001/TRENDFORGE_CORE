"""Exercise preserved research controls independently of page navigation."""

from streamlit.testing.v1 import AppTest


def research_controls_app(kind="backtest"):
    backtest = kind == "backtest"
    return AppTest.from_string(
        "from webapp.runtime import api_client, admin_key_configured\n"
        "from webapp.strategy_catalog import clear_retired_scan_cache\n"
        "from webapp.research_workspace import render_research_workspace\n"
        "clear_retired_scan_cache()\n"
        "render_research_workspace(api_client(), "
        "authorized=admin_key_configured(), "
        f"key={kind!r}, backtest={backtest!r})\n"
    )
