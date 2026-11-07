# Backtesting workspace

The historical page has two dropdowns: **Scanner strategy** and **Stock list**.
Strategy names include their timeframe; history uses that timeframe's default
(60 days intraday, two years swing, five years positional). Stock lists include
official Nifty broad-market and sector indices such as NIFTY PHARMA.

There are two action buttons:

1. **Scan stocks** previews current entry setups and the top candidate names.
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

Completed results show one table of actual entry and exit fills. Columns include
trade number, stock, side, entry time/price/quantity, exit time/price/quantity,
exit reason, costs and net P&L. Partial and final exits have separate rows with
the same trade number. Their closed quantities and allocated costs reconcile to
the completed position. Daily data identifies the candle date, not an exact
intrabar execution time.

Use the table's download icon to export this entry/exit report. Scanner indicator
tables, summary dashboards and result-view dropdowns are absent from this page.
Changing strategy or stock list clears the previous report; failed new runs also
clear it. Older cached results using the reserve policy require a new backtest.
