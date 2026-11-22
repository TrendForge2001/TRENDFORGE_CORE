"""Reference-inspired stock report cards, source labels and paper review link."""

import json
import re

import streamlit as st

from scanner.strategy_horizons import scanner_horizon_choices
from services.stock_report_service import DEFAULTS
from webapp.api_client import ApiError
from webapp.stock_report_document import (
    REPORT_CSS,
    bullets,
    document,
    fundamentals,
    heading,
    hero,
    news,
    source,
    trade_plan,
)
from webapp.ui import render_api_error

WORKSPACE_CSS = """
<style>
[class*="st-key-tf_report_card"] {background:#101015;

border:1px solid #1d1d26;


 border-radius:28px;

padding:22px;

margin:10px 0;

}
.st-key-tf_stock_report_body {background:#050506;

padding:20px;

border-radius:24px;


 padding-bottom:140px;

}
.st-key-tf_stock_report_body [data-testid="stExpander"] details{border:0!important;
background:transparent!important;
}
.st-key-tf_stock_report_body [data-testid="stExpander"] {border:0;

background:transparent;

}
.st-key-tf_stock_report_body [data-testid="stExpander"] summary {font-size:20px;

 background:transparent!important;

}
.st-key-tf_stock_report_body [data-testid="stButtonGroup"] button {
 border-radius:30px;

background:#212026;

min-height:42px;

}
.st-key-tf_stock_report_body [data-testid="stButtonGroup"] button[aria-pressed="true"],
.st-key-tf_stock_report_body [data-testid="stButtonGroup"] button[aria-checked="true"] {
 background:linear-gradient(100deg,#7228e9,#ef077f,#ff682b);

color:white;

}
.st-key-tf_report_actions{position:fixed;

bottom:12px;

left:50%;

transform:translateX(-50%);


 width:calc(100% - 30px);

max-width:1060px;

z-index:999;

padding:12px 16px;


 background:#13111e;

border:1px solid #342c4b;

border-radius:24px;


 box-shadow:0 -8px 35px #0005;

}
.st-key-tf_report_actions [data-testid="stHorizontalBlock"]{
 display:grid;

grid-template-columns:1fr 2fr;

gap:10px;

}
.st-key-tf_report_actions [data-testid="stColumn"]{width:100%!important;

min-width:0!important;

}
.st-key-tf_report_review button{background:#6145ff;

color:white;

border:0;


 border-radius:18px;

min-height:50px;

font-weight:700;

}
@media(min-width:1000px){.st-key-tf_report_actions {left:calc(50% + 150px);


 width:calc(100% - 345px);

}}
@media(max-width:600px){.st-key-tf_stock_report_body{padding:8px 8px 140px;

}
 [class*="st-key-tf_report_card"]{padding:16px 12px;

border-radius:24px;

}}
</style>
"""


def show(fragment):
    st.html('<div class="tf-stock-report tf-r-fragment">' + fragment + "</div>")


def navigation_state(symbol, strategy_id=None, horizon=None):
    values = {
        "tf_selected_stock_symbol": symbol,
        "tf_stock_report_symbol": symbol,
        "reports_section": "Stock report",
    }
    if horizon in {"short_term", "long_term"} and strategy_id:
        choices = scanner_horizon_choices(horizon)
        label = next(
            (k for k, row in choices.items() if row["strategy_id"] == strategy_id), None
        )
        if label:
            values["stock_report_horizon"] = (
                "Long Term" if horizon == "long_term" else "Short Term"
            )
            values["stock_report_strategy_" + horizon] = label
    return values


def open_stock_report(symbol, strategy_id=None, horizon=None):
    st.session_state.update(navigation_state(symbol, strategy_id, horizon))
    st.switch_page("webapp/pages/reports.py")


def report_link(symbols, *, key, strategy_id=None, horizon=None):
    if not symbols:
        return
    with st.container():
        select, action = st.columns([3, 1], vertical_alignment="bottom")
        symbol = select.selectbox(
            "Stock report", list(dict.fromkeys(symbols)), key=key + "_report_stock"
        )
        if action.button("Open report", key=key + "_report_open", width="stretch"):
            open_stock_report(symbol, strategy_id, horizon)


def render_stock_report_workspace(client, *, key="stock_report"):
    from webapp import stock_report_charts as charts

    st.html("<style>" + REPORT_CSS + "</style>" + WORKSPACE_CSS)
    first, second = st.columns([3, 2], vertical_alignment="bottom")
    with first:
        symbol = (
            st.text_input(
                "NSE stock symbol",
                value=st.session_state.get("tf_selected_stock_symbol", ""),
                placeholder="e.g. INDUSTOWER",
                key="tf_stock_report_symbol",
            )
            .strip()
            .upper()
        )
    with second:
        horizon_label = st.segmented_control(
            "Report horizon",
            ["Short Term", "Long Term"],
            default="Short Term",
            key=key + "_horizon",
        )
    horizon = "long_term" if horizon_label == "Long Term" else "short_term"
    choices = scanner_horizon_choices(horizon)
    labels = list(choices)
    default = next(
        (
            i
            for i, label in enumerate(labels)
            if choices[label]["strategy_id"] == DEFAULTS[horizon]
        ),
        0,
    )
    with st.expander("Report strategy & methodology"):
        choice = st.selectbox(
            "Report strategy", labels, index=default, key=key + "_strategy_" + horizon
        )
        st.caption(
            "Uses your approved strategy and actual insti"
            "tutional-trade rating. Public company facts "
            "are display-only. Prices are completed daily"
            " closes, with their dates shown."
        )
    strategy_id = choices[choice]["strategy_id"]
    scope = (symbol, horizon, strategy_id)
    state_key = key + "_saved"
    if st.session_state.get(key + "_scope") != scope:
        st.session_state.pop(state_key, None)
        st.session_state[key + "_scope"] = scope
    if st.button(
        "Generate stock report",
        type="primary",
        key=key + "_generate",
        width="stretch",
    ):
        st.session_state.pop(state_key, None)
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9&._-]{0,29}", symbol) or ".." in symbol:
            st.warning("Enter a valid NSE stock symbol.")
            return
        try:
            with st.spinner("Preparing price, strategy and company evidence…"):
                report = client.get_json(
                    "/reports/stocks/" + symbol,
                    params={
                        "horizon": horizon,
                        "strategy_id": strategy_id,
                        "refresh": True,
                    },
                    timeout=120,
                )
            if (
                report.get("schema_version") != "stock-report-v1"
                or report.get("symbol") != symbol
            ):
                raise ApiError("The backend returned an incomplete stock report")
            st.session_state[state_key] = report
        except ApiError as exc:
            render_api_error(exc, title="Stock report unavailable")
    report = st.session_state.get(state_key)
    if not report:
        st.info("Select a stock to generate its visual research report.")
        return
    with st.container(key="tf_stock_report_body"):
        show(hero(report))
        with st.container(key="tf_report_card_price"):
            st.subheader("Price & pivot references")
            window = st.segmented_control(
                "Chart window",
                ["3 months", "6 months", "1 year"],
                default="6 months",
                key=key + "_window",
            )
            charts.price(
                report,
                count={"3 months": 63, "6 months": 126, "1 year": 252}.get(window, 126),
            )
        show(heading("Overview") + bullets(report["overview"]))
        show(heading("Risks & Trade Plan") + trade_plan(report))
        with st.expander("Approved entry and exit conditions"):
            st.write(report["strategy"]["entry_rules"])
            st.write(report["strategy"]["exit_rules"])
            st.caption(report["registry_version"])
        show(heading("Recent News Drivers") + news(report))
        show(heading("Fundamental insights"))
        company = report["company"]
        with (
            st.container(key="tf_report_card_fundamentals"),
            st.expander("⚡ Fundamentals", expanded=True),
        ):
            show(fundamentals(company))
        with (
            st.container(key="tf_report_card_ownership"),
            st.expander("◕ Shareholding", expanded=True),
        ):
            periods = company.get("shareholding") or []
            period = None
            if periods:
                label = st.selectbox(
                    "Shareholding quarter",
                    [v["period"] for v in periods],
                    index=len(periods) - 1,
                    key=key + "_ownership_period",
                )
                period = next(v for v in periods if v["period"] == label)
            charts.ownership(period)
            show(source(company))
        with (
            st.container(key="tf_report_card_financial"),
            st.expander("▥ Financials", expanded=True),
        ):
            metric = st.segmented_control(
                "Financial measure",
                ["Revenue", "Net profit"],
                default="Revenue",
                key=key + "_measure",
            )
            frequency = st.segmented_control(
                "Statement period",
                ["Yearly", "Quarterly"],
                default="Yearly",
                key=key + "_frequency",
            )
            charts.financial(
                company,
                metric="net_profit_cr" if metric == "Net profit" else "revenue_cr",
                frequency="quarterly" if frequency == "Quarterly" else "annual",
            )
            show(source(company))
        with (
            st.container(key="tf_report_card_participation"),
            st.expander("◉ Price & Volume", expanded=True),
        ):
            view = st.segmented_control(
                "Past price & volume",
                ["Past returns", "Past volume"],
                default="Past returns",
                key=key + "_participation",
            )
            charts.price(report, view="Volume" if view == "Past volume" else "Returns")
        with st.expander("Institutional rating & data coverage"):
            rating = report.get("rating") or {}
            st.write(
                rating.get("reason")
                or "Actual institutional trade evidence is unavailable."
            )
            st.json(
                {
                    k: rating.get(k)
                    for k in (
                        "rating",
                        "score",
                        "data_coverage",
                        "activity_signal",
                        "disclosure_time",
                        "activity_window_end",
                        "as_of",
                    )
                }
            )
            st.caption(
                "Reported holdings and quarterly changes are "
                "not actual trade quantities."
            )
        with st.expander("Download report data"):
            st.download_button(
                "Download report evidence (.json)",
                json.dumps(report, allow_nan=False, default=str),
                symbol + "_report.json",
                mime="application/json",
                on_click="ignore",
            )
    current_setup = paper_review_allowed(report)
    with st.container(key="tf_report_actions"):
        download, review = st.columns([1, 2], vertical_alignment="center")
        download.download_button(
            "Save report",
            document(report),
            symbol + "_TrendForge_Report.html",
            mime="text/html",
            on_click="ignore",
            width="stretch",
        )
        with review:
            if st.button(
                "Review paper trade",
                key="tf_report_review",
                disabled=not current_setup,
                width="stretch",
            ):
                st.session_state["tf_paper_order_symbol"] = symbol
                st.session_state["tf_stock_report_review_notice"] = symbol
                st.switch_page("webapp/pages/paper_session.py")
        if not current_setup:
            st.caption(
                "Paper review opens when the selected strateg"
                "y has a current complete BUY setup."
            )


def paper_review_allowed(report, *, now=None):
    from datetime import UTC, datetime

    from services.trading_calendar import latest_completed_session

    return bool(
        report.get("trade_plan", {}).get("reviewable_setup")
        and report.get("price", {}).get("bar_date")
        == latest_completed_session(now or datetime.now(UTC)).isoformat()
    )
