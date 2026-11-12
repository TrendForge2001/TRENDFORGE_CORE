# Weekly EMA50/100 gap recovery with annual Floor pivots

Owner-approved chart settings: weekly price EMA50/EMA100; Volume EMA30;
gap-down means weekly open below previous weekly close; recovery means a bullish
close above the midpoint of the previous candle's open/close body. Yearly Floor
pivots display up to 20 historical sets, not a 20-year average.

The baseline uses Wilder RSI14 > 50 and MACD12/26/9 above its signal, including
crosses below zero. All entry conditions must pass, with EMA50 > EMA100 and
close > EMA50. A bearish preceding candle is not required. Volume must exceed
its current completed-week EMA30; no 1.5x multiplier is imposed.

## Calendar and reference data

Kite daily candles are grouped Monday-Sunday. Confirmation is conservatively
deferred until Sunday 23:59:59 IST, so special weekend sessions cannot change a
previously admitted Friday signal. Entry is the next observed daily session's
open. The unfinished current week is never eligible. The initial observed week
is discarded and 100 consecutive completed weeks are required for EMA warm-up.
EMA seeding uses the first observed close with recursive adjust=False smoothing;
exact chart seeding parity has not been independently established.

Annual P=(H+L+C)/3, R1=2P-L, R2=P+H-L, S1=2P-H, S2=P-H+L use the preceding
calendar year's daily high, low and final close. The first observed year is
discarded. Reference years require their weekday boundaries and at least 200
observed sessions; incomplete references block the symbol. This is conservative
and can reject years whose first/last weekday was an exchange holiday. It is
not an independent authoritative exchange-calendar completeness check.

The current year's high/low/close never calculate its own pivot set. Entry-year
R2 is frozen for each position, including across later year changes. Twenty
displayed sets do not cause a 20-year provider request.

## Entries, exits and account

The initial stop is one assumed instrument tick below the signal-week low. The
baseline sells the entire position at R2. R1 is reported as a reference; partial
booking and trailing stops are not enabled in this version. Opening gaps and
slippage must preserve stop < actual entry < R2, otherwise the entry is skipped.
Daily candles manage protection; if a daily candle touches both stop and R2,
the stop takes priority. Gap-down stops use the observed open, while gap-up
target exits conservatively use R2. Intrabar exit timestamps identify the daily
session; they are not observed exchange fill times. Final open positions are
closed as END_OF_TEST and disclosed separately from strategy exits.

Each research child has one shared INR100000 account, zero reserve and at most
three positions. Integer-share allocations include entry fees; default costs
are 12 basis points per side and slippage is 5 basis points per side. Existing
portfolio allocation rules apply; this is not a claim of paper sizing parity.
Separate child accounts must not have their returns summed.

## Application and verification

Technical Scanner or Kite Backtesting → Long Term →
**Weekly EMA 50/100 · Gap Recovery · Yearly Floor R2**. Keep the existing stock-list
and backtesting-period controls. Both 2y and 5y selections fetch up to five years
of daily observations for warm-up, while reports retain the selected execution
window and disclose actual coverage. Early history can be warm-up only.
Render batches budget for the full five-year daily fetch, including 2y runs.

Reports are generated server-side for each batch with CSV and Excel entry/exit
downloads and parameter metadata. Scanner BUY is a candidate, SELL is an
existing-long R2 exit indication, and HOLD means no fresh action. The scanner
does not know an individual holding's original stop; historical trade reports
apply the stored stop to each simulated position.

This strategy is research-only and excluded from automatic daily paper scans.
Existing paper strategy identities and their validation version remain intact;
the weekly research implementation has its own `weekly-floor-gap-recovery-v1`
version. No broker writes, paper activation or paper ledger changes are added.

`python -m scripts.verify_weekly_floor --output-dir weekly-floor-verification`
generates artificial target/stop/end-of-test examples through the application
backtest and report pipeline in a temporary database. These examples verify
execution and accounting, not historical profitability or the supplied SBIN
chart. Actual Kite history, split-adjustment parity, point-in-time constituents,
holdouts and forward results net of costs remain separate acceptance evidence.
