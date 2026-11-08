# Backtesting workspace

The historical page has a strategy dropdown within each of five horizon tabs
and one **Stock list** dropdown. Horizons are Intraday, Short Swing (quick
multi-day), Short Term, Medium Term and Long Term. Daily 50/100 is available
under Medium Term; daily 100/200 under Long Term. History defaults to 60 days
intraday, two years for daily swing and five years for Long Term. Stock lists include
official Nifty broad-market and sector indices such as NIFTY PHARMA.

There are two action buttons:

1. **Scan stocks** starts a background scan and records its candidate report.
2. **Backtest** evaluates historical signals across the entire selected list.

Current scan matches do not restrict the historical universe. Stock-list history
is fetched in bounded batches, with up to 1,000 symbols and explicit exclusions
for unavailable/misaligned history. Current constituent membership is used;
historical point-in-time membership has not been reconstructed.

## Historical capital policy

- ₹1,00,000 initial capital; ₹1,00,000 deployment ceiling; **₹0 fixed reserve**.
- At most three concurrent stock positions, with score-proportional budgets.
- Whole shares, 12 bps costs per side and 5 bps adverse slippage per side.
- Existing strategy stop-risk limits remain active. The EMA/pivot model retains
  its 0.5% planned-equity-risk cap; risk sizing and whole shares can leave cash
  uninvested. All available capital is eligible, but fills are not forced.
- The deployment ceiling stays at initial capital; profits do not raise it.
- Selecting a bearish research strategy explicitly labeled **borrow assumed**
  applies that assumption to historical simulation; broker borrow is not checked.

This changes historical simulations. It does not modify paper/live controls or
submit orders. Source entry/exit conditions and chronological fill rules remain
in force. Engine versions change to identify the new capital model.

## Trade report

Completed results appear on the separate **Reports** page, one batch at a time.
The backend generates a detailed CSV and Excel workbook automatically, with one row per actual
exit fill: trade number, stock, side, entry time/price/quantity, exit
time/price/quantity, exit reason, costs and net P&L. Partial and final exits
share a trade number. Their quantities and allocated costs reconcile to the
completed position. Daily data identifies the candle date, not an exact
intrabar execution time.

Runs continue on the backend after leaving the work page. Reports shows batch
progress and offers visible CSV and Excel download buttons above the table after completion. New scans,
selection changes and failed runs do not overwrite previous batch reports.
Scanner exports are labelled indicator snapshots. Historical reports preserve
the capital policy actually used; new runs use zero fixed reserve.

See [strategy horizons, report lifecycle and storage](RESEARCH_BATCH_REPORTS.md)
for API, queue, restart and PC/Render persistence details.
