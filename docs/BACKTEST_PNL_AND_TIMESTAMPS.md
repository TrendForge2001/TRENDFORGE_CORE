# Backtest P&L and entry/exit timestamps

The existing Kite Backtesting tab now has a P&L dashboard for one stock or a
scanner-selected batch. Choose all completed stocks or one stock. It shows
allocated/ending capital, net return, winning/losing trade P&L, trade count,
fees, included slippage, daily realized P&L, equity P&L and drawdown. Summary,
daily statement and trade CSV downloads are available. Existing tabs are kept.

Each stock is an independent allocation. The total return is combined net P&L
divided by combined initial capital, not an average of stock percentages.
Failed simulations are excluded and counted explicitly. Equity curves align
observations in IST, carry forward the latest mark, and hold initial capital
before a stock's first observation. Missing/inconsistent curves do not produce
a combined drawdown. This is an allocation comparison, not a simulation of a
shared trading account or shared execution constraints.

Capital changes must reconcile with engine P&L and the closed-trade ledger
(with paise rounding tolerance). Fees/slippage are already reflected in engine
net P&L. Slippage estimates are disclosed without deducting them twice. Daily
realized P&L uses exit dates in IST; invalid exit dates are excluded from the
daily breakdown and flagged. Missing fees are shown as unavailable, not zero.

Trade tables use `DD Mon YYYY, HH:mm:ss IST`, e.g. `24 Oct 2026, 09:30:00 IST`.
Aware UTC/offset timestamps convert to Asia/Kolkata. Naive market/paper values
follow the existing backend contract: they are interpreted as IST. Ambiguous
non-ISO dates are not guessed. Missing values show an em dash; malformed values
are labelled invalid. Date-only records say that time is unavailable.

Historical fills identify a candle bar, not the precise tick execution time.
Daily backtests therefore show `24 Oct 2026 (daily bar, IST)` instead of claiming
an exact midnight fill. Entry/exit signal timestamps stay distinct from fill
bar timestamps. Exit-before-entry and missing-date evidence is flagged rather
than silently rewritten.

Paper positions/statements, strategy statements, Kite order tables and historical
trade tables use the common formatter. CSV and Excel exports retain original
machine timestamps and add `*_ist` display columns. Original records, timezone
precision, prices, engine rules and persisted trade history are not changed.
Diagnostic JSON remains raw evidence. Spreadsheet formula escaping is retained.
