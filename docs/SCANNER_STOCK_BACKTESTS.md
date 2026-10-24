# Scanner stock backtesting

Open **Kite Backtesting → Scanner matches**. Choose Swing (daily candles) or
Intraday (15-minute candles). The scanner panel shows the actual technical
profile, indicators, entry triggers and risk references used by the existing
canonical scanner and backtest engine.

Select an official Nifty index or sector list (including Bank, Financial Services,
IT, Auto, FMCG, Pharma, Metal, Realty and broad/mid/small/micro-cap indexes).
Filter by sector/industry, optionally select individual stocks, then run a scan.
The grouped LargeMidcap 250 option uses the same official membership with sector
filtering. Lists are cached for ten minutes in the browser session and refreshable.
Missing official membership is reported rather than replaced with a guessed list.

Choose Technical Momentum, EMA 20/50 + RSI + Volume, or VWMA 9/26 + RSI + Volume.
The named variants use the existing registered-strategy evaluators and simulator;
the UI describes their deterministic entry/exit rules. Scores are per stock, with
unavailable scores left blank. There is no minimum-score slider.

Large lists are split into requests of at most 100 stocks without truncation.
A failed batch has explicit errors and blank scores; an authorization failure
stops the scan. You can also reuse the latest completed result from
the Technical Scanner tab in the same signed-in browser session. Select a signal
(default BUY) and stocks. An empty selection never runs a test.
Snapshots from another timeframe are not eligible. Failed scan symbols are excluded.

Set history, capital **per stock**, transaction costs and slippage, then choose
**Backtest selected stocks**. Each selected stock runs an independent historical
simulation through the existing admin-protected `/technical/backtest` API.
Requests are sequential, with progress and separate failure rows. These tests do
not allocate shared portfolio capital or create paper/broker orders. Up to 1000
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
filters do not guarantee future performance. Intraday/swing modes and the three workspace strategy choices are supported.
These research choices do not enable paper entries or live broker execution.

Single-stock backtesting remains available under **Single stock**. The five
navigation tabs and dark theme are preserved. The scanner/condition panel and
results/detail arrangement follow the supplied Streak reference.
