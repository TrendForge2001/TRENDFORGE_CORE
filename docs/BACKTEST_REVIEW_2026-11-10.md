# Review of the three supplied NIFTY 100 reports

These are historical simulations generated on 9 November 2026, not paper fills
or broker orders. All begin with ₹100,000, zero fixed cash reserve, and at most
three concurrent positions. Registry: `ema-pivot-staged-paper-v7-ist-history`.

| Batch prefix | Strategy | Positions / exit fills | Net P&L | Return | Win rate | Profit factor | Maximum drawdown | Fees |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 440e4789 | Intraday Low20 breakdown SHORT | 170 / 170 | −₹21,477.01 | −21.48% | 25.88% | 0.333 | 21.93% | ₹15,733.87 |
| 20888fbe | Intraday EMA9/20 momentum LONG | 109 / 109 | −₹21,862.46 | −21.86% | 22.02% | 0.212 | 22.64% | ₹12,184.45 |
| 324b1848 | Short Swing EMA9/26 bearish pivot | 16 / 21 | −₹280.10 | −0.28% | 37.50% | 0.902 | 1.93% | ₹460.59 |

The two intraday reports share a 940-bar common window, 11 September–9 November
2026. They include 95 stocks; BAJAJHLDNG, ENRIN, TATACAP, TMCV and VAML were
excluded for interior candle-calendar mismatches. Requested history was 60 days.

The swing report requested two years but simulated only **103 common daily
bars, 15 June–9 November 2026**. All 100 stocks were included, so a short common
overlap limited the effective sample. It is not a full two-year validation.
Five positions have partial exits, explaining 21 exit rows for 16 positions.
Gross profit was ₹180.49; fees turned it into a net loss. The report explicitly
assumes short borrow; this assumption does not establish overnight cash-equity
short availability at the broker.

Entry/exit ordering, exit quantities and exported P&L reconcile. Rounded exported
intraday fills differ from summary net P&L by ₹0.06 and ₹0.04 respectively. The
reported slippage impact is already reflected in fill prices and must not be
subtracted again. Uninvested cash caused by quantity/risk limits is not a fixed
cash reserve. Daily-candle timestamps identify bar dates, not exact executions.

None of these samples demonstrates a profitable edge after costs. Do not sum
their P&L as if they were simultaneous strategies sharing one ₹100,000 account.
Compare holdouts and forward account-level paper results after verifying data
coverage, chart conventions, costs and correlated exposure.

## Scanner screenshot

`EXIT` describes a possible exit for an existing position. `WAIT` means no armed
new entry. `research_next_candle_execution_not_paper_enabled` identifies the
research-only entry route; it is not a broker failure and does not establish
that the entire paper service is disabled.

The old exporter dropped `error`, `error_code` and `error_reference` for `ERROR`
rows. New reports preserve those safe diagnostics. Legacy reports are immutable
and cannot recover information never saved. Reports now offers an authenticated
current-input recheck for up to ten failed symbols, including the screenshot's
BIRET, DUMMYHEG and HFCL. It separately checks the current NSE equity instrument
master, completed history and required indicators. An unavailable input remains
blocked; no symbol aliases or price levels are invented.
