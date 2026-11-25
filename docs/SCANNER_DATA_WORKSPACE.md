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

Stock-list selection exists only on Stock Scanner. Its Scan stocks and Stock
report sections share the selected stock context. Watchlists is removed from
navigation; old Watchlists and Scanner bookmarks redirect to the scanner.
The supplied 23 November 2026 CSV contributes 139 index identities, not equity
constituents or live prices. Exact-index NSE membership is fetched separately;
reference-only indices (including volatility and bond indices) cannot be scanned
as equity universes. Missing membership is reported instead of substituting a
different index. Source reachability from Render must be observed separately.

Every completed scanner run is automatically journalled in Reports with all
BUY, SELL, EXIT, WAIT and data-error rows. Reports keeps the latest ten completed
scanner runs. Older scanner payloads and scan archive folders are retired,
including pre-upgrade reports; archive tombstones prevent resurrection after DB
recovery. Backtest evidence, queued stock provenance and paper books are separate
and are not deleted by scanner retention. SQLite pages are reusable; automatic
retention does not perform a blocking full database VACUUM.

BUY/SELL/EXIT results with valid data are copied to the durable Backtesting queue,
with their actual stock, strategy, horizon, source list and scan identity. EXIT
is research of an existing-long closing signal, never permission for a short
entry. Duplicate handoffs are ignored. Backtesting shows strategy name and net
profitability; Start queued backtests runs strategy groups sequentially through
the existing workload/risk checks. Rejected admission leaves the queue available
for retry. A restart requires Start to resume dispatch; it does not auto-start
paper trading. Independent accounts are identified and are never summed into a
single account result. No-trade, flat and loss-making results remain distinct.

The queued-stock Excel contains each stock's strategy. Completed trade Excel
preserves every original simulated trade/evidence sheet plus queue provenance
and account-scope notes. Excel downloads use Office Agile password encryption,
not worksheet protection. By default they use the existing TrendForge login
password; an operator can later set TRENDFORGE_EXCEL_PASSWORD separately. Stored
research evidence/backups are not encrypted by the download wrapper.

Kite Connection requires the TrendForge password again before account data or
preview requests, with a 15-minute, server-held signed unlock and a Lock action.
TRENDFORGE_KITE_WINDOW_PASSWORD can override the shared password later. Password
rotation invalidates outstanding window unlocks. Existing owner/API protection
still applies. This window gate does not interrupt market-data access or the
independent paper worker. Multiple-account OAuth/login is deferred; no new user
accounts or broker-order capability are introduced.

Paper remains a separate strategy-readiness workspace. Scanner selection,
reports, backtest starts and profitability never activate paper entries or
change its account limits or order state. Approved strategy rules are unchanged.

A failed independent research partition now identifies its child batch and
safe diagnostic code. The parent stays failed; completed child reports remain
available and their independent portfolio P&L is not combined.

Verification uses synthetic portfolios and temporary databases. Browser checks
cover all seven active pages at 1440 px and 390 px, private imports/exports, both source
availability and Moneycontrol-denied recovery, and paper form preservation.
Synthetic screenshots are previews, not account or performance evidence.
Live public source observation is a separate CI job and does not establish
reachability from Render. No private workbook is included in source or CI.

Paper Trading contains Open positions, Trade reports and Strategy readiness.
Trade reports defaults to All time and reads every saved closed fill, including
partial exits; it does not use the former 200-row workspace preview or the
scanner's ten-run retention. Period filters use the realised exit date in IST.
Parent IDs attribute partial realised P&L and buy/sell flows to an open position.
Its cumulative flows include partial legs and must not be added a second time
to the separate closed-fill totals. Recorded fees/cost bases are preserved.
Downloads retain an encrypted compact ledger and full recorded fill evidence.

Position tables and the stock report summary use only LTP, OPEN PRICE,
CLOSE PRICE, TARGET, STOPLOSS, EXCHANGE, QTY, SEGMENT, REALISED P&L,
UNREALISED P&L, BUY VALUE and SELL VALUE. Stock identity is the row label;
closed rows also identify their exit time and fill ID. OPEN/CLOSE are actual
entry/exit fills in paper history and proposed entry/profit-exit levels in a
stock research report. Unknown quantities, quotes, targets and P&L stay blank.
A closed fill's exit price is not shown as a current LTP. Kite open net rows use
the broker's average entry cost; a flat net row has no inferred trade chronology.

For stocks lacking a complete approved strategy plan, reports also calculate an
independent conditional reference from 20 completed daily sessions. Entry is
the 20-session high plus 0.1%, support stop is the 20-session low minus 0.1%,
and the projected target is entry plus twice the entry-to-stop distance (2R).
Confirm a daily breakout, RSI14 above 50, above-average volume and the relevant
EMA trend before considering entry. Dated/stale and insufficient evidence is
labelled. These are planning references, not current BUY signals or execution
plans. They do not overwrite approved strategy entries, exits, yearly targets,
readiness, risk limits or paper admission. The quoted LTP is separately sourced
and timestamped; the historical chart continues to use completed daily closes.
# Scanner session freshness

Daily evaluations use the latest completed NSE session. The operational calendar
includes the 2026 cash-market closures published in
[NSE/CMTR/71775](https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf).
Saved operator holidays are added; explicit special sessions override published
closures. Invalid saved calendars still block execution. These dates are not
inferred from missing candles, and historical admission snapshots remain frozen.
Subsequent exchange amendments and other years require verified calendar updates.

At 11:30 IST on 25 November 2026 the expected daily candle is 23 November,
because 24 November was a holiday. After the 25 November close, that day's candle
is required. Genuine stale results display WAIT with a stale-data explanation;
the original setup signal remains in the saved audit evidence. Diagnostics show
expected/received session dates and the reason for an unavailable combined
rating. Missing actual institutional trades remain `NO_TRADE_DATA`, never an
invented BUY/SELL activity or combined score. Existing saved scans are snapshots;
run a new scan to evaluate with the corrected calendar.
