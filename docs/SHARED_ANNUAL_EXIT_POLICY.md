# Shared annual conditional exit policy

Policy: `shared-annual-conditional-exits-v1`  
Registry: `strategy-v10-shared-annual-conditional-exits`

The owner approved applying the daily VWMA exit policy to the nineteen retained
strategies below. Entry indicators stay native to each strategy. The already
updated daily VWMA 20/50 and weekly EMA 50/100 recovery strategies retain their
existing rules. Revised strategies are research only and are not approved for
new paper entries. This release does not start automation or submit broker orders.

## Strategy roles

| Strategy ID | Revised role |
| --- | --- |
| `tf_intraday_ema9_20_momentum` | Long entry; 15-minute confirmation |
| `tf_intraday_vwma9_26_rsi_volume` | Long entry; 15-minute confirmation |
| `tf_swing_ema20_50_rsi_volume` | Long entry; daily confirmation |
| `tf_swing_vwma9_26_rsi_volume` | Long entry; daily confirmation |
| `tf_ema9_26_bullish_pivot` | Long entry; native EMA/RSI/MACD/pivot filters |
| `tf_ema20_50_bullish_pivot` | Long entry; native EMA/RSI/MACD/pivot filters |
| `tf_ema50_100_bullish_pivot` | Long entry; native EMA/RSI/MACD/pivot filters |
| `tf_ema100_200_bullish_pivot` | Long entry; native EMA/RSI/MACD/pivot filters |
| `tf_intraday_ema9_20_short` | Bearish signal exits an existing long only |
| `tf_intraday_vwma9_26_short` | Bearish signal exits an existing long only |
| `tf_intraday_vwap_breakdown_short` | Bearish signal exits an existing long only |
| `tf_intraday_low20_breakdown_short` | Bearish signal exits an existing long only |
| `tf_intraday_ema_adx_continuation_short` | Bearish signal exits an existing long only |
| `tf_ema9_26_bearish_pivot` | Bearish signal exits an existing long only |
| `tf_ema20_50_bearish_pivot` | Bearish signal exits an existing long only |
| `tf_ema50_100_bearish_pivot` | Bearish signal exits an existing long only |
| `tf_ema100_200_bearish_pivot` | Bearish signal exits an existing long only |
| `tf_medium_ema50_100` | Entry review only; momentum thresholds await owner input |
| `tf_long_ema100_200` | Entry review only; momentum thresholds await owner input |

Exit-only rules have no short bracket and cannot run as standalone entry
backtests. A borrow declaration cannot enable them. Their original bearish setup
is the exit signal; their former bullish short-cover condition is not a long exit.
The two review-only entries receive the common exit specification but no invented
RSI-20 or MACD entry filter. Existing scanner menu choices remain unchanged.

## Annual reference and entries

Use previous calendar-year daily H/L/C:

- `P = (H + L + C) / 3`
- `R1/R2/R3 = P + (0.382/0.618/1.0) × (H − L)`
- `S1/S2/S3 = P − (0.382/0.618/1.0) × (H − L)`

Fetch five years of daily history for annual reference and warm-up. Intraday
RSI and volume still use completed native 15-minute candles. Intraday history
alone never supplies annual H/L/C. Discard the first observed reference year;
require at least 200 daily sessions and January/December boundary coverage.
This is a coverage check, not an independent exchange-calendar completeness audit.
Twenty pivots back is display history, not a twenty-year averaging rule.

Freeze annual levels from the signal year for each position. Generic entries fill
at the next observed candle open plus slippage. EMA/pivot entries retain the
strict next-candle-only trigger above the signal candle high. ATR brackets and
the old ATR-based 1.5R traditional-pivot headroom gate are replaced by annual
reference sizing. Native traditional-P location filters remain in place.

Recompute the second **distinct positive yearly pivot strictly below actual fill**.
For a fill of 110, P=100, S1=90 and S2=80, the initial conditional reference is 90.
Reject entries without two lower levels, without ordered R1/R2/R3, or at/above R1.

## Combined protective exits

Either complete group triggers an exit:

```text
A = RSI_WILDER_14 < 30 AND current_open < previous_candle_close
B = current_close < current_open
    AND current_volume > current_volume_SMA20
    AND current_close < conditional_support_reference
EXIT = A OR B
```

Use native daily candles for swing/positional rules and native 15-minute candles
for intraday rules, as confirmed by the owner. Group A compares adjacent native
candle prices. An opening fill can use only the previous completed RSI. If RSI
first confirms at the current candle close, exit at the next observed open.
Group B always requires a completed close. A support breach alone never exits.
A red candle and total volume proxy selling participation; OHLCV does not reveal
actual aggressor-side selling quantities.

Confirmed native bearish setups also exit existing longs at the next open.
Bullish EMA/pivot strategies use their corresponding complete bearish setup;
native crossover rules require the opposite crossover with RSI/volume confirmation.
No former ATR hard stop, single-indicator exit, or short entry is substituted.

## Profit booking, sizing and intraday completion

- Sell `floor(initial_quantity / 2)` at yearly R1, with the remaining quantity
  assigned to R2/R3. At least two whole shares are required at entry.
- When R2 is reached, continue toward R3 only after a completed close strictly
  above R2 with volume strictly above SMA20. Otherwise exit the remainder at the
  next observed open. R3 is the final known-in-advance sell limit.
- After the R1 partial, high-volume completed closes above R1/R2 may raise the
  conditional reference to the cleared level for following candles. Never lower
  it. It remains conditional on the combined groups, not a resting stop order.
- Intraday positions square off at the 15:00 IST candle open and never carry
  overnight. Missing square-off history fails the simulation rather than
  fabricating an overnight fill. An unfinished final session is liquidated at
  the end of the selected test window.
- The historical shared account uses INR100000, zero reserve and at most three
  stocks. Size using 0.5% marked equity against reference distance plus fees;
  this planned reference risk is not a guaranteed maximum loss. Apply whole
  shares, fees and slippage. Reconcile partial fills to gross/net P&L and cash.

## Validation and compatibility

All public current-policy backtest routes use `AnnualExitBacktestEngine`, sharing
the approved daily simulator. Exit-only and review-only rules are blocked before
standalone backtesting. Registry revision invalidates previous promotion evidence;
new paper admission remains blocked even if a caller claims validation passed.
Existing positions keep their earlier exit lineage; this change does not rewrite
stored stops. Opt-in `previous_exit_policy` test fixtures replay legacy ATR/short
contracts separately from new-policy public-route tests. Synthetic execution
checks are not evidence of profitability.
