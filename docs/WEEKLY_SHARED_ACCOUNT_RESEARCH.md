# Weekly account comparison specification — 14 November 2026

The next weekly backtest runs four comparisons, in order, against the same stock
histories and NIFTY 100 price-index observations. NIFTY 100 is the initial default
stock list; the existing backtesting-period selector remains. No paper or broker
orders are created and no automation policy is changed.

| Stage | Admission changes |
| --- | --- |
| shared_account_baseline | One ₹100,000 account, zero reserve, three positions; retain legacy score-weighted allocation as control. |
| risk_sizing | 1% current-equity planned risk, 33.33% per-stock entry notional, three simultaneous positions, 3% aggregate initial planned open risk. |
| stop_distance_10pct | Add structural stop distance ≤10% of slipped entry fill. |
| target_room_1_5R | Add net reward / planned risk ≥1.5 to frozen entry-year R2. |

The first stage is intentionally the unsized control. Stage two changes the sizing
and portfolio risk bundle; stage three and four add one filter each. The filters
are proposed research settings, not established improvements.

For a long entry, `F = next open × 1.0005`, `S = original structural stop`,
`T = frozen R2`, `c = 0.0012`, `s = 0.0005`:

- Planned loss/share = `F × (1+c) − S × (1−s) × (1−c)`.
- Net reward/share = `T × (1−s) × (1−c) − F × (1+c)`.
- Quantity = floor of the minimum of risk, entry-notional, cash including entry
  fee, and remaining aggregate-risk allowances. Equity is marked at observable
  opening prices (last known close only for absent stocks), never that day's
  future close. Each admission records its equity, cash, bracket and allowances.

Risk is frozen entry-to-stop planned loss including both fees and normal
slippage. The aggregate cap is tested against current equity at new admission.
It does not force liquidation when equity falls later. Allocation is capped at
entry; winners are not mechanically rebalanced. Actual adverse gaps can exceed
planned risk. Additional 1%, 3% and 5% gap scenarios remain deferred.

History is fetched in bounded chunks into one chronological simulation per
comparison. Fetch boundaries never reset money or position slots. Render admits
NIFTY 100's five-year warm-up within its 150,000-observation worker budget. Larger
universes that exceed that budget are rejected for a PC full-account run; they
are never silently split into independently capitalized accounts. Scanner batches
and explicit legacy API simulations retain their previous behavior.

Each stock computes its own completed-week indicators and annual Floor pivots
from its own history. Warm-up is applied at each signal, so new listings do not
truncate established stocks. Missing stock sessions cannot create fills; last
marks carry stale flags. The original signal conditions, next-session timing,
structural stop, frozen R2, 12 bps fees and 5 bps slippage are retained. Decimal
tick arithmetic fixes a binary-rounding defect that could subtract an unintended
extra tick from an exactly tick-aligned signal-week low; no stop rule is widened
or tightened.

Reports include the ordered metric changes, profit factor, skip counts/reasons,
largest winner and top-five share of gross positive P&L, net profit excluding
the largest one/five winners, all four trade ledgers, one daily equity series per
comparison, daily drawdown/exposure/open risk, and NIFTY 100 benchmark comparison.
The benchmark is a price index without dividends or implementation costs and is
not an entry filter. Missing coverage is explicitly flagged; no constituent
average is substituted for the index. Current constituents still introduce
survivorship limitations; point-in-time membership is not claimed.

Daily equity is marked before forced terminal liquidation. Terminal closes,
cost drag and the bridge to final cash are reported separately. A stale terminal
mark is a disclosed valuation assumption, not evidence of an executable price.
Winner/P&L metrics include terminal liquidation and also disclose terminal versus
prior strategy-exit P&L. Excel includes comparisons, daily equity, all variant
trades, terminal liquidations, entry audit, skipped entries, benchmark and stock
coverage. CSV remains the final-stage trade ledger; JSON retains the campaign.

Index EMA40, stronger volume, trailing stops, time exits and additional gap shocks
are not included in this first comparison. Artificial CI data validates mechanics
only. Real NIFTY 100 profitability requires the authenticated historical-data run.
