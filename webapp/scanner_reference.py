"""Readable strategy condition chart and source-linked scanner reference downloads."""

import io
import json
import zipfile
from pathlib import Path

import streamlit as st

from scanner.multi_strategy_engine import REVIEW_REQUIRED
from scanner.strategy_registry import list_strategies
from services.research_report import csv_report


def condition_rows():
    return [
        {
            "Strategy": row["name"],
            "Strategy ID": row["strategy_id"],
            "Modes": ", ".join(row["modes"]),
            "Candles": ", ".join(row["intervals"]),
            "Indicators": ", ".join(row["indicators"]),
            "Registered entry conditions": " | ".join(row["entry_rules"]),
            "Registered exit conditions": " | ".join(row["exit_rules"]),
            "Limitations": " | ".join(row["ambiguities"] + row["notes"]),
            "Availability": "Dedicated weekly scanner/backtest; paper disabled"
            if row["implementation_status"] == "dedicated_research"
            else "Review only"
            if row["strategy_id"] in REVIEW_REQUIRED
            else "Executable rules; paper validation still required",
        }
        for row in list_strategies()
    ]


def reference_pack():
    path = Path(__file__).resolve().parents[1] / "config/public_scanner_templates.json"
    return json.loads(path.read_text(encoding="utf-8"))


def reference_zip():
    pack = reference_pack()
    rows = condition_rows()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("public_templates.json", json.dumps(pack, indent=2))
        archive.writestr(
            "scanner_conditions.csv",
            csv_report(rows, list(rows[0])).encode("utf-8-sig"),
        )
        archive.writestr(
            "README.txt",
            "Public reference templates, not native Streak/Screener exports.\n"
            "Source URLs and verification limits accompany each template.\n"
            "These references do not register or enable execution strategies.\n"
            "The condition chart describes registry rules; declared notebook "
            "rules can differ from implemented evaluators.\n"
            "In particular, EMA20/50's undefined reversal/low-volume exits "
            "and staged notebook targets are not fully implemented.\n"
            "Validate parameters, data conventions, entries, exits and risk "
            "before implementing any external template.\n",
        )
        for template in pack["templates"]:
            archive.writestr(
                "templates/" + template["id"] + ".txt",
                template["name"]
                + "\n"
                + template["conditions"]
                + "\n"
                + template["source_url"]
                + "\n"
                + template["limitations"]
                + "\n",
            )
    return buffer.getvalue()


def render_scanner_reference():
    with st.expander("Scanner conditions, indicators and template downloads"):
        st.caption(
            "Registry condition chart. Declared notebook rules can differ from "
            "implemented evaluators; validation remains required. EMA20/50's "
            "undefined reversal/volume exits and staged notebook targets "
            "are incomplete."
        )
        rows = condition_rows()
        st.dataframe(rows, hide_index=True, width="stretch")
        st.download_button(
            "Download scanner condition chart (CSV)",
            csv_report(rows, list(rows[0])).encode("utf-8-sig"),
            "trendforge_scanner_conditions.csv",
            "text/csv",
        )
        st.caption(
            "Six public references: three Streak examples/adaptations and three "
            "Screener.in queries. These are reference downloads, not native "
            "platform exports or newly enabled trading strategies."
        )
        st.dataframe(reference_pack()["templates"], hide_index=True, width="stretch")
        st.download_button(
            "Download scanner reference templates (ZIP)",
            reference_zip(),
            "trendforge_scanner_references.zip",
            "application/zip",
        )
