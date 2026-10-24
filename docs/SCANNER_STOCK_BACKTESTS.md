# Scanner stock backtesting

Open **Kite Backtesting → Scanner matches**. Choose Swing (daily candles) or
Intraday (15-minute candles). The scanner panel shows the actual technical
profile, indicators, entry triggers and risk references used by the existing
canonical scanner and backtest engine.

Run a scan for up to 100 NSE symbols, or reuse the latest completed result from
the Technical Scanner tab in the same signed-in browser session. Select a signal
(default BUY), minimum score and stocks. An empty selection never runs a test.
Snapshots from another timeframe are not eligible. Failed scan symbols are excluded.

Set history, capital **per stock**, transaction costs and slippage, then choose
**Backtest selected stocks**. Each selected stock runs an independent historical
simulation through the existing admin-protected `/technical/backtest` API.
Requests are sequential, with progress and separate failure rows. These tests do
not allocate shared portfolio capital or create paper/broker orders. Up to 100
stocks can take several minutes; keep the browser session open until completion.

Compare return, trades, net profit, win rate, drawdown and profit factor per
stock. Select a stock to inspect its ledger and equity observations. Export the
comparison or combined trade CSV. CSV exports neutralize spreadsheet formulas.
Batch evidence includes the scanner profile, selection snapshot, scan run ID,
scan observation time when available, cost assumptions and history. Each
successful stock result is stored by the existing backtest repository; the batch
comparison is kept in browser session state, so export it before signing out.

The latest scan selects stocks using information from today and then backtests
them historically. This introduces selection bias: this is not a reconstruction
of historical index membership or a point-in-time scanner portfolio. Failed or
unavailable history is reported as a failure, never zero performance. Scanner
filters do not guarantee future performance. Intraday/swing canonical profiles
are supported; arbitrary saved-strategy rules are not substituted for them.

Single-stock backtesting remains available under **Single stock**. The five
navigation tabs and dark theme are preserved. The scanner/condition panel and
results/detail arrangement follow the supplied Streak reference.
