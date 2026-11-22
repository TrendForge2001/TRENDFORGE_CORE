# Scanner data and workspace recovery

The Stock Scanner starts with daily Short Term strategies and combines technical
signals, actual institutional activity, stock ratings and data coverage in one
result view. All nine approved bullish scanner strategies remain available in
their respective horizons. This release does not change trading rules, risk
limits, admission policy or automation state.

Candle fetches preserve individual source errors. At most three omitted or
transient stock responses are retried once in each bounded fetch batch, using
the same provider. Authentication failures and rate limits are not immediately
retried. Unresolved symbols, missing history, warm-up requirements and stale
candles have separate fixed diagnostics. Provider exception bodies are not
shown. A weekly strategy still requires 100 completed weeks and annual pivots;
a new listing is not treated as a source outage or given a fabricated score.

NSE disclosures are fetched independently when Moneycontrol holdings are
unavailable, including before the first investor workbook import. A cold-start
preview contains at most 100 returned public records and is explicitly
unfiltered. Only exact matches to tracked investors or verified aliases affect
Big Shark activity. Quarterly holdings changes never stand in for actual buys
and sells. Missing publication timestamps stay Unknown. Failed requests retain
last good data with its original source and dates.

Every page uses the shared stock list, sidebar navigation, full-width content
and normal page scrolling. Watchlists has compact My watchlists / Discover rows.
Stock Scanner shows results inline; Institutional Data contains separate public
feeds, private imports and activity/evidence tabs. Advanced run settings,
source aliases and diagnostics are collapsed. Paper positions are shown before
setup details; kill controls and explicit Start/Stop safeguards are retained.
Reports retains gross P&L, costs, net P&L and verified exports.

A failed independent research partition now identifies its child batch and
safe diagnostic code. The parent stays failed; completed child reports remain
available and their independent portfolio P&L is not combined.

Verification uses synthetic portfolios and temporary databases. Browser checks
cover all eight pages at 1440 px and 390 px, private imports/exports, both source
availability and Moneycontrol-denied recovery, and paper form preservation.
Synthetic screenshots are previews, not account or performance evidence.
Live public source observation is a separate CI job and does not establish
reachability from Render. No private workbook is included in source or CI.
