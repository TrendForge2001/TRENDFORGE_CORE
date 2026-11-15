# Daily VWMA 20/50, RSI and yearly Fibonacci breakout

Strategy ID: `tf_daily_vwma20_50_rsi_fibonacci_yearly`  
Engine version: `daily-vwma-yearly-fibonacci-v1`

Select **Daily VWMA 20/50 · RSI · Yearly Fibonacci Breakout** on Scanner or
Backtesting, select the stock list/history and choose **Scan stocks** or
**Backtest**. Reports stores the resulting condition snapshot or reconciled
entry/exit CSV and Excel workbook. This is daily long-only research.

## Indicators

- Daily NSE session candles, evaluated after session end at 15:30 IST.
- VWMA(n) = sum(close × volume, n) / sum(volume, n), for n=20 and n=50.
- RSI14 uses Wilder smoothing seeded with a 14-observation SMA.
- Volume SMA20 includes the completed signal candle, matching the earlier
  proposed scanner default. The screenshot's volume EMA option is not this
  baseline; an EMA run must be treated as a separately versioned variant.
- Annual Fibonacci pivots use the previous completed calendar year's H/L/C.
  P=(H+L+C)/3; D=H−L; R1/R2/R3=P+(0.382/0.618/1.0)D;
  S1/S2/S3=P−(0.382/0.618/1.0)D. They remain fixed within a year.
- Twenty pivots back is a chart-display setting, not a 20-year averaging window.

## Entry conditions — all confirmations required

1. Close > VWMA20 > VWMA50.
2. VWMA20 > previous VWMA20 AND VWMA50 > previous VWMA50.
3. 55 ≤ RSI14 ≤ 75.
4. Volume ≥ 1.5 × volume SMA20, and the average is positive.
5. At least one fresh breakout:
   - Previous close ≤ a yearly P/R1/R2/R3 and signal close > that same level;
     ignore this branch on the first observed session of a new calendar year.
   - Previous close ≤ the maximum high of the preceding 20 sessions and signal
     close > that high. The signal candle is excluded from the high calculation.
6. Daily indicator warm-up and previous-year reference coverage are valid.

A manually drawn channel cannot be reproduced from the image without its date
and price anchors. The prior-high test supplies an objective price breakout.
There is no invented Fibonacci R4 above R3 and no pivot-based profit target.

## Entry order, stop and exits

- At signal close arm a buy stop at signal high × 1.003, rounded up to the
  instrument tick. Default assumed tick is INR0.05, recorded in reports.
- The order is valid for the next observed daily session only. Expire it if
  that session's high never reaches the trigger; never fill on signal close.
- A gap above the trigger fills at the higher of open/trigger, plus adverse
  slippage. Recalculate quantity and targets from the actual simulated fill.
- Fixed initial stop = minimum low of five sessions including the signal
  × 0.997, rounded down to the tick. Never widen or recenter that stop.
- R = actual entry − fixed initial stop. Sell floor(original quantity/2) at
  entry + 2R; sell the remainder at entry + 3R. Keep the original stop after
  the partial exit; this version does not add a break-even stop.
- Completed close < VWMA20 schedules the remainder's exit for next open.
  RSI <45 alone does not exit.
- Protective stops act intrabar. Gap-through stops fill at open with adverse
  slippage. If daily OHLC cannot resolve sequence, active stops take priority
  over profit targets, including the entry bar.
- Force remaining positions closed at the final test close, with costs.

## Account assumptions and evidence

Use TrendForge's shared historical INR100000 account, zero fixed reserve,
INR100000 deployment ceiling and at most three concurrent stocks. Rank on
completed-signal score, then symbol; allocate budgets by score. Integer shares,
at least two per entry, and a 0.5% marked-equity planned risk cap per trade,
including entry/stop exit fees. Default costs: 12 bps per side; adverse slippage:
5 bps per side. Gaps can exceed the planned loss cap.

Fetch five years of daily history to calculate references before cutting the
execution window to the chosen 1y/2y/5y. Discard the first observed calendar
year; a reference year requires at least 200 observed sessions, a first
session by January 10 and a last session on/after December 20. This tolerates
holidays but does not independently audit exchange-calendar completeness.
Never substitute an older year for a missing preceding year. Stock-list
membership is current membership; no point-in-time universe reconstruction.
Cloud capacity may divide a large daily universe into explicitly separate
portfolio batches; assess each report's actual account scope and date range.

Daily timestamps identify sessions, not exact intrabar fill times. Synthetic
tests establish implementation behavior, not profitability or chart-provider
parity. Strategy registration asserts no historical performance. Paper and
broker execution are disabled for this research strategy.
