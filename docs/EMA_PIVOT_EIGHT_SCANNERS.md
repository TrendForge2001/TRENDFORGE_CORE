# Eight owner-specified EMA / RSI / MACD / traditional-pivot scanners

Added 1 November 2026. These are research rules supplied by the owner, not Streak
presets or historically validated recommendations. The eight new configurations
are available in the existing Technical Scanner and Kite Backtesting tabs. The
original six definitions and five intraday short counterparts remain registered.
The catalog now has 19 definitions: nine existing paper candidates, eight new
research scanner/backtest configurations and two original review-only definitions.

| Scanner ID suffix (`tf_` prefix) | Setup | RSI | MACD | Initial stop | Partial / remainder |
|---|---|---|---|---|---|
| `ema9_26_bullish_pivot` | Fresh bullish EMA 9/26 cross, close above both | 55–70 | Above signal; histogram positive and rising | Entry − 1.5 ATR | Half at 1R, stop to entry, final 2R |
| `ema9_26_bearish_pivot` | Fresh bearish EMA 9/26 cross, close below both | 30–45 | Below signal; histogram negative and falling | Entry + 1.5 ATR | Half at 1R, stop to entry, final 2R |
| `ema20_50_bullish_pivot` | Fresh bullish EMA 20/50 cross, close above both | 50–65 | Above signal and zero | Entry − 2 ATR | Half at 1.5R, stop to entry, final 3R |
| `ema20_50_bearish_pivot` | Fresh bearish EMA 20/50 cross, close below both | 35–50 | Below signal and zero | Entry + 2 ATR | Half at 1.5R, stop to entry, final 3R |
| `ema50_100_bullish_pivot` | EMA 50 > 100; candle range touches EMA 50, closes above | Cross above 50 | Above signal; histogram rising | Entry − 2 ATR | Half at 2R, trail remainder |
| `ema50_100_bearish_pivot` | EMA 50 < 100; candle range touches EMA 50, closes below | Cross below 50 | Below signal; histogram falling | Entry + 2 ATR | Half at 2R, trail remainder |
| `ema100_200_bullish_pivot` | Fresh bullish EMA 100/200 cross, close above both | 50–70 | Above signal and zero | Entry − 3 ATR | Half at 3R, trail remainder |
| `ema100_200_bearish_pivot` | Fresh bearish EMA 100/200 cross, close below both | 30–50 | Below signal and zero | Entry + 3 ATR | Half at 3R, trail remainder |

All eight support 15-minute intraday and daily swing research. The 100/200 pair
also appears under Position. Its daily reference is the previous month in either
daily view; the other daily pairs use the previous week. Every intraday pair uses
the previous NSE session. Inputs are completed candles only; crossover conditions
compare the latest two completed candles, not any cross in a lookback window.
Intraday indicator values carry across sessions, so the first completed 09:15 bar
can cross against the previous session's last bar and arm a 09:30 entry trigger.

## Indicators and pivots

New columns `RSI_WILDER_14` and `ATR_WILDER_14` use an initial 14-observation SMA
followed by Wilder smoothing. EMA 26 is added; MACD retains 12/26 EMA lines and a
9-period EMA signal. Existing strategies retain their earlier RSI/ATR calculations.
At least slow-EMA-length + 1 observations are required for a new setup.

Traditional reference levels are P = (H+L+C)/3, R1 = 2P−L, R2 = P+(H−L),
S1 = 2P−H and S2 = P−(H−L). Reference OHLC aggregation uses IST dates and entirely
preceding periods. The first observed period is discarded because it may be
partial. An intraday prior-session reference requires all 25 normal-session
15-minute bars, 09:15 through 15:15. Missing weekly/monthly periods do not fall
back to an older period. Missing reference levels block a setup. Exchange holiday
calendars and special sessions are not reconstructed; the strict normal-session
coverage rule can exclude special-session data.

Longs require close > P and shorts close < P. The next directional pivot among
P/R1/R2/S1/S2 must offer at least 1.5R from the proposed entry. If price has moved
beyond every available level in that direction, the plan explicitly reports
“No further level in P/R1/R2/S1/S2”; it does not invent another resistance/support.
The scanner shows the actual EMA, RSI, MACD, ATR, volume-average and pivot values.

The optional volume filter is OFF by default. When enabled, signal volume must
be strictly greater than 1.5 times the preceding 20 candles' average, excluding
the signal candle. This is not a same-time-of-day volume comparison.

## Entry plans and historical simulation

BUY/SELL with `entry_state=ARMED` describes a setup, not a filled order. The
entry trigger is the next tick strictly above the signal high or below its low.
Tick size is a visible research assumption, default ₹0.05; it must be set to suit
the instrument. The application does not claim that every NSE instrument uses
that tick size. The trigger expires after the next available candle, whether or
not it trades through the trigger. A fresh setup is required to arm another.
Intraday triggers require the immediate next 15-minute candle in the same session,
with entry before 14:45 IST. Intraday positions exit at the 15:00 bar open; missing
that square-off bar makes the result unavailable rather than carrying overnight.

Gap entries fill at the worse of the next open or trigger, with configured
slippage. Stops and profit levels are anchored to the actual entry using the
signal ATR. The pivot-room filter is checked again at that fill; failing entries
are skipped. Price-based R multiples exclude fees. Sizing includes entry and
planned stop-exit fees in a maximum 0.5% of marked account equity per trade;
gaps/slippage can still exceed planned risk. Short simulations require an explicit
available-borrow assumption. This is not verification of a lender or broker.

Backtests retain the shared ₹1,00,000 account, ₹80,000 deployment ceiling,
₹20,000 entry cash floor and three concurrent stocks. Signal scores determine
proportional budgets; all checks passing produces equal 100 scores, hence equal
budgets for simultaneous matches. Risk caps and whole shares may leave much of
the budget unused. The reserve is not deliberately reinvested; losses can reduce
cash below the reserve. Shorts lock full notional collateral and their sale
proceeds are never reused. A symbol has at most one open position in a run.
The interface runs one scanner at a time, so it does not combine multiple scanner
books or count overlapping signals as separate positions.

Partial exits sell/cover floor(quantity/2), with the odd share left in the
remainder. Entries requiring fewer than two shares are skipped. For 50/100 and
100/200 positions, the trailing stop updates after each completed candle from
the highest/lowest close since entry minus/plus three times that candle's ATR.
It only tightens and becomes active on the next candle. There is no fabricated
fixed final reward/risk for a trailing remainder.

Indicator exits are close below/above the fast EMA; 9/26 also exits on the
opposing MACD/signal cross, and 20/50 also exits at RSI < 45 for longs or > 55
for shorts. They execute at the following open. Active stops take priority over
profit levels in ambiguous OHLC bars. After a partial exit, a new breakeven stop
may also execute on the same candle if its range crosses entry, a conservative
assumption because the intrabar sequence is unknown. Tests force-close residual
positions at the final historical candle.

The portfolio P&L dashboard includes an Exit fills view/export. Daily P&L uses
actual partial/final exit dates and prorates entry costs to each fill. Trade
counts refer to completed stock positions, not individual exit legs. Skip reasons
and execution assumptions appear in Run details. Daily timestamps are labelled
as daily bars; minute-level event times inside daily bars are not invented.
Intrabar exit timestamps identify the source candle's start in IST, not the
unknown tick time at which an OHLC-derived fill would have occurred.

## Paper and deployment boundaries

All eight have `paper_eligible=false`. Their staged exits/trailing stops are
implemented for historical simulation, not for the live paper ledger. They cannot
be selected for automatic paper Start, and full paper-strategy validation reports
their explicit research-only exclusion. The existing nine paper candidates keep
their validation, storage, market-data, capital, freshness and kill-switch gates.
No Kite broker permissions are added and no order is submitted by scanning or
backtesting. The registry version changes, so existing paper automation must
obtain validation covering the current catalog before admitting entries.

GitHub's main-branch workflow verifies the exact commit served by Render and the
Streamlit proxy after all test/security jobs pass. A local Windows installation
requires a separate source update and restart; a Render deploy does not update
the owner's PC or attach persistent cloud storage.

## Verification scope

Tests exercise all eight long/short rules, missing/warm-up values, causal pivot
and volume references, next-candle expiry, gap rejection, staged exits, stops,
trailing and 15:00 square-off, risk/capital constraints, costs and P&L conservation,
admin API handling, the existing screens and SQLite result read-back. These are
synthetic functional checks. No current Kite historical-performance results,
profitability claims, live fills or owner-PC runtime checks are implied.

Release verification also identified four current advisories against the existing
`pyasn1==0.6.4` dependency. Production and PC locks use the published fixed version
`0.6.5`. The dependency audit still checks every locked package without ignores.
