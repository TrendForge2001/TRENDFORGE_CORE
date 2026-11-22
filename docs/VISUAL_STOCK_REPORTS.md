# Visual stock research reports

Reports → Stock report provides the reference-style report for one NSE equity.
Stock Scanner and Watchlists have Open report actions. The Fundamentals page
uses the same report, without enabling new fundamental screening rules.

The layout includes a combined-rating card, completed-close price chart,
approved strategy trade references, factual indicator overview, sourced news,
fundamental ratio cards, dated ownership, annual/quarterly revenue and profit,
and past price return/volume charts. Controls update the saved report view
without re-running the scanner or sources. Save report downloads a standalone,
printable HTML document; the evidence JSON is available separately.

Kite supplies price history and the existing approved scanner supplies trade
levels and institutional ratings. Company figures are display-only public
Screener observations; consolidated/standalone basis, fetched time, period ends
and unknown ratio observation dates are shown. Financial amounts are displayed
only when ₹ crore units are explicit. Sector P/E remains unavailable when the
source does not report it. Incomplete ownership totals never become a normalized
pie, future/open statement periods and TTM-as-a-year are excluded, and actual
losses and zero values remain visible. News requires a recent dated source link;
date-only publication records do not receive an invented time.

The report is a current snapshot, not evidence of historical disclosure timing.
It cannot promote a strategy, change approved entries/exits, enable automation
or submit orders. The paper-review action selects the symbol and navigates to
the existing supervised paper page. It does not pre-fill an invented resting
stop, bypass risk checks, arm automation or unlock broker orders. Research-only
strategies do not enable paper review. Indicator-trailing strategies are not
assigned fabricated fixed profit targets.

The report cache changes when the latest completed market session changes.
Explicit report generation rechecks the technical data even within the cache
window. Public company facts use a bounded 32-symbol, one-hour cache, and retain
their actual fetch time. All API report reads require the private admin API
credential; the owner web session is also required on the hosted app.

Tests and browser previews use synthetic data, temporary databases and no broker
client or owner workbook. The separate public-company source observation uses
INDUSTOWER only as a public example and does not establish Render reachability.

Reports request a bounded evidence payload from the real scanner: the price
chart, technical component and condition checklist use the same completed daily
candles. They do not issue a second stock-history request. Stale-candle status
remains visible even when research execution is separately disabled.

The existing 60-point technical component can be displayed without institutional
disclosures. Its points and thresholds are shared with the combined rating.
Missing or stale actual bought/sold disclosures leave the combined rating
unrated, with the reason and coverage shown. They never become zero institutional
flows or inferred BUY/SELL activity. Entry references, pending confirmations,
existing-long exit signals and invalid plans are labeled separately; current
indicator/pivot references remain available without inventing a new entry plan.

Kite quote previews still require quotes no older than 60 seconds. Missing,
invalid or stale quote payloads return a specific HTTP 409 data blocker with
zero orders submitted, rather than a generic service-outage message.
