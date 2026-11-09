# Kite history request correction and candle integrity

Based on merged release `d5c53bfe88f0`.

Historical requests now convert timezone-aware instants to `Asia/Kolkata` at the
REST request boundary before formatting Kite's timezone-free date parameters.
This covers provider, adapter and direct client callers. Naive timestamps retain
the exchange-local contract, and date-only inputs remain date-only. UTC dates,
year rollover and offset-bearing strings have transport-level regression tests.

Previously, a request at 11:50 IST could send an end time of 06:20, which excluded
the current trading session. The corrected request returns current-day candles;
the existing completed-bar filter still removes the candle that is forming.

## Trace and genuine recovery attempts

The read-only diagnostic records the historical response before candle parsing,
then compares provider timestamps, normalized timestamps and completed-bar
timestamps. It also makes bounded full-session, targeted 15-minute and targeted
one-minute reads for the 15:15 period. It never submits orders or prints keys.
Raw candle responses and response hashes stay in the selected local directory;
the diagnostic does not change the paper ledger or insert replacement bars.

For example, from PowerShell with the existing PC Python environment:

```powershell
python -m scripts.trace_kite_history --data-dir "$env:LOCALAPPDATA\TrendForgeCore" --session 2026-11-06 --symbols RELIANCE TCS --output-dir "$env:LOCALAPPDATA\TrendForgeCore\reports\history-trace"
```

Run it with the same Python environment and credentials used by the PC launcher.
Choose an earlier completed session within the selected 30/60-day history period.
Keep raw responses outside the source checkout.

The observed 6 November RELIANCE and TCS session had 24 bars at every stage:

| Stage | Bars in the session | 15:15 present |
| --- | ---: | --- |
| Raw successful Kite response | 24 | No |
| Provider parsing | 24 | No |
| OHLCV normalization | 24 | No |
| Completed-bar filtering | 24 | No |
| Targeted 15:15–15:30 read, 15-minute interval | 0 | No |
| Targeted 15:15–15:30 read, one-minute interval | 0 | No |

The absent bar is upstream of normalization and filtering. Kite explains that
CAS-eligible equities end continuous trading at 15:15 and their closing-auction
period has no intraday candles through the historical API. See
[Kite's explanation](https://kite.trade/forum/discussion/16324/kite-connect-historical-api-missing-last-15-minutes-of-nse-intraday-data)
and [NSE's CAS information](https://www.nseindia.com/market-data/closing-auction-session).

The existing 25-bar pivot requirement is preserved. No 15:15 candle is invented,
interpolated, copied from daily OHLC, or reconstructed from an empty minute
response. Pipeline regressions verify that a genuine 15:15 bar survives with
its original OHLCV, and a 24-bar session stays incomplete with invalid pivots.
Under the unchanged requirement, these CAS samples remain ineligible. Complete
genuine evidence or an independently reviewed strategy/session policy change
is required before that blocker can pass.

## Retiring faulty-window validation

The catalog version is now `ema-pivot-staged-paper-v7-ist-history`. Completed
snapshots from earlier contracts become `invalidated`; they provide no restored
promotion evidence and cannot be exported as the current validation. Their
original SQLite run records remain intact for audit. Valid current-contract
snapshots still survive a restart.

Stop any running validation started with the old request window before updating
the PC code. Do not reuse its results. Restart full NIFTY 500 validation through
the existing background workflow only after the historical-data correction and
required session completeness checks pass. The live CAS samples above still
fail the preserved completeness requirement, so a new run must remain pending.

Paper automation remains subject to existing validation, freshness and risk
admission. This repair does not enable broker writes or change account limits.
