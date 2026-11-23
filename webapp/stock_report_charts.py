"""Responsive interactive charts over the report's sourced observations."""

import altair as alt
import pandas as pd
import streamlit as st

from webapp.stock_report_document import PALETTE, esc, money


def price(report, *, count=126, view="Price"):
    rows = report.get("candles", [])[-count:]
    if len(rows) < 2:
        st.info("Completed daily candle history is unavailable.")
        return
    frame = pd.DataFrame(rows)
    if view == "Volume":
        field, title, color = "volume", "Shares traded", "#a48cff"
    elif view == "Returns":
        frame["price_return"] = (frame.close / frame.close.iloc[0] - 1) * 100
        field, title, color = "price_return", "Price return (%)", "#a48cff"
    else:
        field, title, color = (
            "close",
            "Daily close (₹)",
            "#3cce6a" if frame.close.iloc[-1] >= frame.close.iloc[0] else "#ff6377",
        )
    base = (
        alt.Chart(frame)
        .mark_line(color=color, strokeWidth=2.5)
        .encode(
            x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %y", tickCount=4)),
            y=alt.Y(field + ":Q", title=title, scale=alt.Scale(zero=view != "Price")),
            tooltip=[
                alt.Tooltip("date:T", title="Completed candle", format="%d %b %Y"),
                alt.Tooltip(field + ":Q", title=title, format=",.2f"),
            ],
        )
    )
    layers = [base]
    if view == "Price":
        from services.conditional_stock_plan import display_plan

        plan = display_plan(report)
        levels = [
            {"label": label, "value": value, "color": color}
            for label, value, color in [
                ("Stoploss reference", plan.get("stop_reference"), "#ff6377"),
                (
                    "Conditional entry" if plan.get("basis") else "Entry reference",
                    plan.get("entry"),
                    "#a48cff",
                ),
                ("Last close", frame.close.iloc[-1], "#efb83f"),
                (
                    "2R target" if plan.get("basis") else "Target",
                    next((v for v in plan.get("targets", []) if v is not None), None),
                    "#3cce6a",
                ),
            ]
            if value is not None
        ]
        rules = (
            alt.Chart(pd.DataFrame(levels))
            .mark_rule(strokeDash=[5, 4])
            .encode(
                y=alt.Y(
                    "value:Q", title="Daily close (₹)", scale=alt.Scale(zero=False)
                ),
                color=alt.Color("color:N", scale=None, legend=None),
                tooltip=["label:N", alt.Tooltip("value:Q", format=",.2f")],
            )
        )
        layers.append(rules)
        st.html(
            '<div class="tf-stock-report tf-r-fragment"><div class="tf-r-levels">'
            + "".join(
                '<span><i class="tf-r-dot" style="background:'
                + row["color"]
                + '"></i>'
                + esc(row["label"])
                + "<strong>"
                + money(row["value"])
                + "</strong></span>"
                for row in levels
            )
            + "</div></div>"
        )
    chart = (
        alt.layer(*layers)
        .properties(height=270)
        .configure_view(stroke=None)
        .configure_axis(labelColor="#bdb9cc", titleColor="#bdb9cc", gridColor="#282530")
    )
    st.altair_chart(chart.properties(background="#101015"), width="stretch", theme=None)
    st.caption(title + " · " + report["price"]["source"] + " · Completed candles only.")


def ownership(period):
    if not period or not period.get("complete"):
        st.info(
            "A complete dated ownership breakdown is unav"
            "ailable. Missing categories are not estimate"
            "d."
        )
        return
    frame = pd.DataFrame(period["categories"])
    frame["category_label"] = [
        f"{row['category']} · {row['percent']:.2f}%" for row in period["categories"]
    ]
    chart = (
        alt.Chart(frame)
        .mark_arc(innerRadius=65, outerRadius=108)
        .encode(
            theta=alt.Theta("percent:Q"),
            color=alt.Color(
                "category_label:N",
                scale=alt.Scale(
                    domain=frame["category_label"].tolist(),
                    range=list(PALETTE)[: len(frame)],
                ),
                legend=alt.Legend(
                    title=None,
                    orient="bottom",
                    columns=2,
                    labelLimit=180,
                    labelColor="#c6c1d6",
                ),
            ),
            tooltip=[
                alt.Tooltip("category:N", title="Reported category"),
                alt.Tooltip("percent:Q", title="Holding (%)", format=".2f"),
            ],
        )
        .properties(height=300)
        .configure_view(stroke=None)
    )
    st.altair_chart(chart.properties(background="#101015"), width="stretch", theme=None)
    st.caption(
        "Reported ownership · "
        + period["period"]
        + " · Period end "
        + period["period_end"]
    )


def financial(company, *, metric="revenue_cr", frequency="annual"):
    rows = [row for row in company.get(frequency, []) if row.get(metric) is not None][
        -5:
    ]
    if not rows:
        st.info("No sourced statement series with verified ₹ crore units is available.")
        return
    frame = pd.DataFrame(rows)
    frame["value"] = frame[metric]
    base = alt.Chart(frame).encode(
        x=alt.X(
            "period:N",
            sort=[r["period"] for r in rows],
            title=None,
            axis=alt.Axis(labelAngle=0, labelLimit=85),
        ),
        y=alt.Y("value:Q", title="₹ Cr", scale=alt.Scale(zero=True)),
        tooltip=["period:N", alt.Tooltip("value:Q", title="₹ Cr", format=",.2f")],
    )
    bars = base.mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5).encode(
        color=alt.condition(
            alt.datum.value >= 0, alt.value("#2cc63f"), alt.value("#ff6377")
        )
    )
    text = base.mark_text(dy=-12, color="#e9e5f2", fontSize=11).encode(
        text=alt.Text("value:Q", format=",.0f")
    )
    chart = (
        (bars + text)
        .properties(height=280)
        .configure_view(stroke=None)
        .configure_axis(labelColor="#bdb9cc", titleColor="#bdb9cc", gridColor="#282530")
    )
    st.altair_chart(chart.properties(background="#101015"), width="stretch", theme=None)
    st.caption(
        "All values in ₹ Cr · " + (company.get("reporting_basis") or "Basis unknown")
    )
