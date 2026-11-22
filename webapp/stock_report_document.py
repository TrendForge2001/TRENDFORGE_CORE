"""Shared report visuals and standalone export. No external fonts or scripts."""

import html
import math
from datetime import datetime
from zoneinfo import ZoneInfo

from services.stock_report_service import finite, safe_url

PALETTE = ("#5741ff", "#ff9e20", "#ff516f", "#bc42d7", "#46caa7", "#79b3ff")
REPORT_CSS = """
.tf-stock-report{font-family:Inter,system-ui,sans-serif;

color:#f3f2f8;

background:#050506;


 line-height:1.65;

padding:24px;

border-radius:24px;

box-sizing:border-box;

}
.tf-stock-report *{box-sizing:border-box;

}
.tf-r-label{color:#aaa8b8;

font-size:12px;

letter-spacing:.07em;

text-transform:uppercase;

}
.tf-r-fragment{padding:0!important;
background:transparent;
border-radius:0;
}
.tf-r-heading{width:fit-content;
max-width:100%;
background:linear-gradient(100deg,#7732ff 0%,#ea008a 40%,#ff702c 75%,#efbd24);


 color:transparent;

background-clip:text;

font-size:34px;

font-weight:800;

line-height:1.2;


 margin:35px 0 22px;

letter-spacing:-.04em;

}
.tf-r-card{background:#101015;

border:1px solid #1d1d26;

border-radius:28px;

padding:26px;


 margin:18px 0;

break-inside:avoid;

}
.tf-r-hero{background:#20202d;

}
.tf-r-top{display:flex;

justify-content:space-between;

align-items:center;

gap:12px;

}
.tf-r-identity{display:flex;

gap:15px;

align-items:center;

}
.tf-r-icon{display:grid;

place-items:center;

background:#eeeefa;

color:#262332;


 width:58px;

height:58px;

border-radius:18px;

font-weight:800;

font-size:18px;

}
.tf-r-name{font-size:23px;

line-height:1.3;

font-weight:750;

}
.tf-r-company{font-size:14px;

color:#b6b4c1;

}
.tf-r-price{font-size:28px;

font-weight:750;

margin:12px 0;

}
.tf-r-pill{display:inline-block;

padding:5px 12px;

border-radius:30px;

background:#33323d;


 color:#d2d0de;

font-size:12px;

margin:6px 5px 0 0;

}
.tf-r-verdict{text-align:center;

min-width:130px;

background:#302b49;

border:1px solid #534775;


 padding:23px 18px;

border-radius:25px;

color:#e2dbff;

}
.tf-r-verdict strong{display:block;

font-size:25px;

line-height:1.3;

}
.tf-r-verdict.buy{background:linear-gradient(140deg,#bcffa8,#30d54e);

color:#17351e;

border:0;

}
.tf-r-verdict.exit{background:#ffcccf;

color:#75222c;

border:0;

}
.tf-r-verdict small{display:block;

margin-bottom:7px;

font-size:12px;

}
.tf-r-grid{display:grid;

grid-template-columns:repeat(2,minmax(0,1fr));

gap:12px;

}
.tf-r-metric{background:#303034;

padding:17px 18px;

border-radius:20px;

}
.tf-r-metric span{display:block;

color:#cbc9d2;

font-size:14px;

}
.tf-r-metric strong{font-size:21px;

line-height:1.4;

}
.tf-r-note{color:#a9a7b8;

font-size:12px;

margin-top:12px;

overflow-wrap:anywhere;

}
.tf-r-title{font-size:20px;

font-weight:650;

margin-bottom:18px;

}
.tf-r-levels{display:flex;

justify-content:space-between;

gap:16px;

flex-wrap:wrap;


 margin-bottom:15px;

font-size:13px;

}
.tf-r-levels strong{display:block;

font-size:18px;

}
.tf-r-list{padding-left:22px;

margin:15px 0;

}
.tf-r-list li{margin:0 0 17px;

padding-left:4px;

}
.tf-r-news a,.tf-r-note a{color:#c6b8ff;

text-decoration:none;

}
.tf-r-news{padding:15px 0;

border-bottom:1px solid #26232d;

}
.tf-r-svg{width:100%;

height:auto;

display:block;

overflow:visible;

}
.tf-r-legend{display:flex;

gap:16px;

flex-wrap:wrap;

font-size:13px;

}
.tf-r-dot{width:9px;

height:9px;

border-radius:50%;

display:inline-block;

margin-right:6px;

}
.tf-r-empty{color:#a9a7b8;

border:1px dashed #393441;

padding:24px;

border-radius:18px;

}
@media(max-width:600px){.tf-stock-report{padding:16px;

border-radius:18px;

}
 .tf-r-card{padding:20px 16px;

border-radius:24px;

}.tf-r-heading{font-size:28px;

}
 .tf-r-top{align-items:flex-start;

flex-wrap:wrap;

}.tf-r-name{font-size:20px;

}
 .tf-r-verdict{min-width:110px;

padding:17px 15px;

}.tf-r-verdict strong{font-size:20px;

}
 .tf-r-metric{padding:14px 12px;

border-radius:17px;

}.tf-r-metric strong{font-size:18px;

}}
@media print{body{background:#fff!important;

} .tf-stock-report{padding:0;

}
 .tf-r-card{break-inside:avoid;

}a{color:inherit!important;

}@page{margin:12mm;

}}
"""


def esc(value):
    return html.escape(str(value if value is not None else "Unavailable"))


def indian_number(value, decimals=2):
    value = finite(value)
    if value is None:
        return "Unavailable"
    integer, _, fraction = f"{abs(value):.{decimals}f}".partition(".")
    last = integer[-3:]
    prefix = integer[:-3]
    groups = []
    while prefix:
        groups.insert(0, prefix[-2:])
        prefix = prefix[:-2]
    text = ",".join([*groups, last])
    return ("-" if value < 0 else "") + text + ("." + fraction if decimals else "")


def money(value):
    return "₹" + indian_number(value) if finite(value) is not None else "Unavailable"


def stamp(value):
    try:
        return (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            .astimezone(ZoneInfo("Asia/Kolkata"))
            .strftime("%d %b %Y · %H:%M IST")
        )
    except (AttributeError, TypeError, ValueError):
        return "Unknown"


def heading(text):
    return '<h2 class="tf-r-heading">' + esc(text) + "</h2>"


def card(title, content):
    return (
        '<section class="tf-r-card"><div class="tf-r-title">'
        + esc(title)
        + "</div>"
        + content
        + "</section>"
    )


def empty(text):
    return '<div class="tf-r-empty">' + esc(text) + "</div>"


def source(company):
    url = safe_url(company.get("source_url"))
    link = (
        '<a href="'
        + esc(url)
        + '" target="_blank" rel="noopener noreferrer">'
        + esc(company.get("source"))
        + "</a>"
        if url
        else esc(company.get("source") or "Unavailable")
    )
    return (
        '<div class="tf-r-note">Source: '
        + link
        + " · "
        + esc(company.get("reporting_basis") or "Basis unknown")
        + "<br>Fetched "
        + stamp(company.get("fetched_at"))
        + " · Ratio observation date: "
        + esc(company.get("facts_as_of") or "Unknown")
        + "</div>"
    )


def hero(report):
    rating = report.get("rating") or {}
    verdict = rating.get("rating") or "UNRATED"
    if verdict in {"INSUFFICIENT_DATA", "NO_DATA"}:
        verdict = "UNRATED"
    tone = (
        "buy"
        if verdict in {"BUY", "STRONG_BUY"}
        else "exit"
        if verdict == "EXIT"
        else ""
    )
    technical = report.get("technical") or {}
    price = report["price"]
    symbol = report["symbol"]
    return (
        (
            '<section class="tf-r-card tf-r-hero"><div cl'
            'ass="tf-r-top"><b>TRENDFORGE</b><span class='
            '"tf-r-note">'
        )
        + stamp(report.get("generated_at"))
        + (
            '</span></div><br><div class="tf-r-top"><div>'
            '<div class="tf-r-identity"><span class="tf-r'
            '-icon">'
        )
        + esc(symbol[:2])
        + '</span><div><div class="tf-r-name">'
        + esc(symbol)
        + '</div><div class="tf-r-company">'
        + esc(report["company_name"])
        + '</div></div></div><div class="tf-r-price">'
        + money(price.get("value"))
        + '</div><div class="tf-r-note">'
        + esc(price.get("basis"))
        + " · "
        + esc(price.get("bar_date"))
        + '</div><span class="tf-r-pill">'
        + esc(report["horizon"].replace("_", " ").title())
        + '</span><span class="tf-r-pill">Technical: '
        + esc(technical.get("signal"))
        + '</span></div><div class="tf-r-verdict '
        + tone
        + '"><small>Combined rating</small><strong>'
        + esc(verdict.replace("_", " "))
        + '</strong></div></div><div class="tf-r-note">'
        + esc(report["strategy"]["name"])
        + "<br>Ratings and entry triggers are evaluated separately.</div></section>"
    )


def price_chart(report, count=126, *, view="Price"):
    rows = report.get("candles", [])[-count:]
    if len(rows) < 2:
        return empty("Completed candle history is unavailable.")
    close = [row["close"] for row in rows]
    values = (
        [row["volume"] for row in rows]
        if view == "Volume"
        else [(v / close[0] - 1) * 100 for v in close]
        if view == "Returns"
        else close
    )
    plan = report["trade_plan"]
    levels = (
        [
            ("Support", plan.get("support"), "#2cce55"),
            ("Last close", close[-1], "#f8b53e"),
            ("Resistance", plan.get("resistance"), "#ff526d"),
        ]
        if view == "Price"
        else []
    )
    available = [v for _, v, _ in levels if v is not None]
    low = (
        min([0, *values]) if view in {"Volume", "Returns"} else min(values + available)
    )
    high = max(values + available)
    span = high - low or max(abs(high), 1) * 0.05
    low -= span * 0.08
    high += span * 0.14

    def y(value):
        return 255 - (value - low) / (high - low) * 225

    points = " ".join(
        f"{30 + i * 620 / (len(values) - 1):.2f},{y(v):.2f}"
        for i, v in enumerate(values)
    )
    color = (
        "#a48cff"
        if view == "Volume"
        else "#3dd773"
        if values[-1] >= values[0]
        else "#ff657a"
    )
    lines = "".join(
        (
            f'<line x1="30" x2="650" y1="{y(v):.2f}" '
            f'y2="{y(v):.2f}" stroke="{color}" '
            f'stroke-dasharray="5 4"/><text x="30" '
            f'y="{y(v) - 8:.2f}" fill="{color}" '
            f'font-size="11">{esc(label)} · '
            f"{esc(money(v))}</text>"
        )
        for label, v, color in levels
        if v is not None
    )
    units = (
        "Shares traded"
        if view == "Volume"
        else "Return (%) from first displayed close"
        if view == "Returns"
        else "Daily close (₹)"
    )
    return (
        '<svg class="tf-r-svg" viewBox="0 0 680 300" role="img" aria-label="'
        + esc(units)
        + '"><title>'
        + esc(units)
        + '</title><polyline points="'
        + points
        + '" fill="none" stroke="'
        + color
        + '" stroke-width="2.8"/>'
        + lines
        + '<text x="30" y="286" fill="#9996a9" font-size="11">'
        + esc(rows[0]["date"])
        + (
            '</text><text x="650" y="286" text-anchor="en'
            'd" fill="#9996a9" font-size="11">'
        )
        + esc(rows[-1]["date"])
        + '</text></svg><div class="tf-r-note">'
        + esc(units)
        + " · "
        + esc(report["price"]["source"])
        + ". Lines show available pivot references from the selected strategy.</div>"
    )


def fundamentals(company):
    values = company.get("metrics") or {}
    items = [
        ("P/E ratio", values.get("pe"), ""),
        ("Sector P/E", values.get("sector_pe"), ""),
        ("Dividend yield", values.get("dividend_yield_pct"), "%"),
        ("Market cap", values.get("market_cap_cr"), " Cr"),
    ]
    cells = []
    for label, value, suffix in items:
        text = (
            "Unavailable"
            if value is None
            else ("₹" if suffix == " Cr" else "")
            + indian_number(
                value, 0 if suffix == " Cr" and float(value).is_integer() else 2
            )
            + suffix
        )
        cells.append(
            '<div class="tf-r-metric"><span>'
            + esc(label)
            + "</span><strong>"
            + esc(text)
            + "</strong></div>"
        )
    return '<div class="tf-r-grid">' + "".join(cells) + "</div>" + source(company)


def ownership_chart(period):
    if not period or not period.get("complete"):
        return empty(
            "A complete dated ownership breakdown is unav"
            "ailable. Missing categories are not estimate"
            "d."
        )
    circumference = 2 * math.pi * 85
    offset = 0
    slices = []
    legends = []
    for i, row in enumerate(period["categories"]):
        length = row["percent"] / 100 * circumference
        color = PALETTE[i % len(PALETTE)]
        slices.append(
            f'<circle cx="130" cy="130" r="85" fill="none" '
            f'stroke="{color}" stroke-width="42" '
            f'stroke-dasharray="{length:.3f} '
            f'{circumference - length:.3f}" '
            f'stroke-dashoffset="{-offset:.3f}" '
            f'transform="rotate(-90 130 130)"/>'
        )
        legends.append(
            '<span><i class="tf-r-dot" style="background:'
            + color
            + '"></i>'
            + esc(row["category"])
            + f" · {row['percent']:.2f}%</span>"
        )
        offset += length
    return (
        (
            '<svg class="tf-r-svg" style="max-width:310px'
            ';margin:auto" viewBox="0 0 260 260" role="im'
            'g" aria-label="Reported shareholding percent'
            'ages">'
        )
        + "".join(slices)
        + (
            '<text x="130" y="128" fill="#f2eff8" text-an'
            'chor="middle" font-size="17" font-weight="70'
            '0">'
        )
        + esc(period["period"])
        + (
            '</text><text x="130" y="150" fill="#aaa6b9" '
            'text-anchor="middle" font-size="11">Reported'
            ' ownership</text></svg><div class="tf-r-lege'
            'nd">'
        )
        + "".join(legends)
        + '</div><div class="tf-r-note">Period end: '
        + esc(period["period_end"])
        + " · Ownership changes are not actual trade quantities.</div>"
    )


def financial_chart(company, *, metric="revenue_cr", frequency="annual"):
    rows = [
        row for row in company.get(frequency, []) if finite(row.get(metric)) is not None
    ][-5:]
    if not rows:
        return empty(
            "No sourced statement series with verified ₹ crore units is available."
        )
    values = [row[metric] for row in rows]
    low, high = min(0, min(values)), max(0, max(values))
    span = high - low or 1

    def y(value):
        return 235 - (value - low) / span * 175

    base = y(0)
    bars = []
    for i, row in enumerate(rows):
        x = 40 + i * 610 / len(rows)
        v = row[metric]
        top = min(base, y(v))
        height = max(abs(y(v) - base), 0.5)
        width = min(60, 430 / len(rows))
        color = "#2bc63f" if v >= 0 else "#ff526d"
        bars.append(
            f'<rect x="{x:.2f}" y="{top:.2f}" '
            f'width="{width:.2f}" height="{height:.2f}" '
            f'rx="6" fill="{color}"/><text '
            f'x="{x + width / 2:.2f}" y="{top - 12:.2f}" '
            f'text-anchor="middle" fill="#eeeaf5" '
            f'font-size="12">{v:,.2f}</text><text '
            f'x="{x + width / 2:.2f}" y="270" '
            f'text-anchor="middle" fill="#aaa6b9" '
            f'font-size="12">{esc(row["period"])}</text>'
        )
    return (
        '<div class="tf-r-note" style="text-align:right">All values in ₹ Cr · '
        + esc(company.get("reporting_basis") or "Basis unknown")
        + (
            '</div><svg class="tf-r-svg" viewBox="0 0 680'
            ' 290" role="img" aria-label="Reported financ'
            'ial statement chart"><line x1="25" x2="650" '
            'y1="'
        )
        + f"{base:.2f}"
        + '" y2="'
        + f"{base:.2f}"
        + '" stroke="#95929f"/>'
        + "".join(bars)
        + "</svg>"
    )


def bullets(items):
    return (
        '<ul class="tf-r-list">'
        + "".join("<li>" + esc(item) + "</li>" for item in items)
        + "</ul>"
    )


def trade_plan(report):
    plan = report["trade_plan"]
    fields = [
        ("Entry reference", plan.get("entry")),
        ("Exit reference", plan.get("stop_reference")),
        ("First target", plan["targets"][0]),
        ("Second target", plan["targets"][1]),
        ("Final target", plan["targets"][2]),
    ]
    fields = [
        (label, value)
        for label, value in fields
        if value is not None or label in {"Entry reference", "Exit reference"}
    ]
    grid = (
        '<div class="tf-r-grid">'
        + "".join(
            '<div class="tf-r-metric"><span>'
            + esc(label)
            + "</span><strong>"
            + money(value)
            + "</strong></div>"
            for label, value in fields
        )
        + "</div>"
    )
    return (
        grid
        + '<div class="tf-r-note">'
        + esc(plan.get("entry_order_type") or "No complete entry plan")
        + " · Proposed strategy references, not executed fills.</div>"
        + bullets(
            list(report["strategy"]["stoploss_rules"])
            + list(report["strategy"]["target_rules"])
            + report["risk_notes"]
        )
    )


def news(report):
    if not report.get("news"):
        return empty(
            "No recent, dated source articles are availab"
            "le. No news driver is inferred."
        )
    return "".join(
        '<div class="tf-r-news"><a target="_blank" rel="noopener noreferrer" href="'
        + esc(item["url"])
        + '">'
        + esc(item["title"])
        + '</a><div class="tf-r-note">'
        + esc(item["source"])
        + " · "
        + (
            stamp(item["published_at"])
            if item.get("published_at")
            else esc(item.get("publication_date")) + " · time unknown"
        )
        + "</div></div>"
        for item in report["news"]
    )


def document(report):
    company = report["company"]
    ownership = company.get("shareholding") or []
    content = (
        hero(report)
        + card("Price & pivot references", price_chart(report))
        + heading("Overview")
        + bullets(report["overview"])
        + heading("Risks & Trade Plan")
        + trade_plan(report)
        + heading("Recent News Drivers")
        + news(report)
        + heading("Fundamental insights")
        + card("⚡ Fundamentals", fundamentals(company))
        + card(
            "Shareholding",
            ownership_chart(ownership[-1] if ownership else None) + source(company),
        )
        + card(
            "Financials · Yearly revenue", financial_chart(company) + source(company)
        )
        + card("Price & Volume · Shares traded", price_chart(report, view="Volume"))
    )
    return (
        (
            '<!doctype html><html lang="en"><meta charset'
            '="utf-8"><meta name="viewport" content="widt'
            'h=device-width,initial-scale=1"><title>'
        )
        + esc(report["symbol"])
        + (
            " · TrendForge stock report</title><style>bod"
            "y{margin:0;background:#050506;max-width:1000"
            "px;margin:auto}"
        )
        + REPORT_CSS
        + '</style><article class="tf-stock-report">'
        + content
        + '<p class="tf-r-note">Research / paper workspace · '
        + esc(report["registry_version"])
        + "</p></article></html>"
    )
