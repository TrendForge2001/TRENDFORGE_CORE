# Shared-account backtesting and stock evidence

The Kite Backtesting tab now uses one historical portfolio account rather than
independent ₹1,00,000 allocations for each selected stock.

| Policy | Value |
|---|---|
| Initial total account | ₹1,00,000 |
| Maximum entry capital committed, including entry fees | ₹80,000 |
| Cash reserved from new entries | ₹20,000 |
| Maximum concurrent stock positions | 3 |
| Allocation | Proportional to the selected entry signal scores |
| Quantity | Whole shares affordable after costs and adverse fill slippage |

Choose an approved source strategy and up to 100 candidate symbols from an
official Nifty list/sector. More than three candidate symbols may be evaluated;
only three may be held at once. Larger lists require an explicit smaller
selection, never silent truncation. In **Scanner matches**, the current saved
scanner supplies the candidate universe, not historical scores or fill prices.
WAIT/EXIT rows may be researched historically without becoming entry signals.

At each completed historical candle, the backend re-evaluates the same approved
strategy independently for each candidate. Only BUY or registered intraday SELL signals with finite positive
scores and valid entry/stop/target brackets qualify. It ranks score descending,
then actual reward/risk descending, then symbol ascending for deterministic ties.
Only the top candidates fitting currently vacant slots are considered.

For a group of new entries:

```text
available budget = min(80,000 − existing entry capital committed,
                       available cash − 20,000)
stock budget = available budget × stock score / sum(selected entry scores)
```

Equal scores produce equal budgets. The current rules often give every valid
entry a score of 100 because all entry checks must pass; the UI must not invent
different scores to imply a stronger ranking. Existing holdings are not resized
to rebalance weights. Fewer eligible/affordable stocks mean unused money stays
in cash. Profits do not increase the ₹80,000 cap. Losses may reduce the budget.
This fixed rupee policy applies to backtesting. Paper automation separately
reserves 20% of its configured capital and caps committed entry notional at 80%;
its other admission limits remain independent. Neither path enables broker orders.

## Historical execution

- Entry/technical-exit decisions use completed bars and fill at the next bar open.
  A signal's future outcome is not used for ranking or sizing.
- Entry prices include adverse slippage. Source ATR risk distance is fixed at
  the signal, then bracket levels are rebased to the entry fill. A nonpositive
  rebased stop is rejected. Stops are not widened after entry.
- Known next-open strategy exits can release capital before new entries at that
  open. Intrabar stop/target proceeds cannot finance that bar's earlier opens.
- If one candle touches stop and target, stop wins. Adverse stop gaps use the
  opening price; exit slippage and costs still apply.
- Intraday entries use 09:30–14:45 IST, with strategy-specific later starts still
  applied. Positions square off at the 15:00 candle open. Missing required
  square-off evidence rejects the result rather than simulating overnight carry.
  Pending intraday entries cannot cross sessions or missing 15-minute bars.
- Any position still held at the test boundary closes at the final candle close,
  explicitly recorded as END_OF_TEST. These are bar-based simulations, not exact
  exchange-tick execution timestamps.
- Stocks must have aligned candle coverage over their common available window
  with at least 60 completed bars. A missing/failed candidate history or an
  interior alignment gap rejects the portfolio rather than silently dropping
  the stock or fabricating prices.

The default assumptions remain 12 basis points transaction cost per side and
5 basis points adverse slippage per side, editable in the form. Slippage is
already included in fills and is not subtracted a second time. The cash reserve
earns no simulated interest. The simulation supports long and registered
intraday short strategies, without leverage. A short reserves its full entry
notional as collateral; sale proceeds cannot finance another entry. On cover,
collateral plus directional P&L minus exit costs returns to cash.

## Risk/reward and indicators

The scanner shows each stock's actual strategy score, entry reference, stop,
target, candle timestamp, indicator values and execution-block reason. A missing
indicator/price is unavailable, not zero. Values include the selected source
strategy's EMA or VWMA levels, RSI 14, volume MA20, ATR, close and volume.

```text
long risk/share = entry − stop; reward/share = target − entry
short risk/share = stop − entry; reward/share = entry − target
risk:reward = 1 : (reward per share / risk per share)
```

These are gross price-based ratios, not win probabilities or promised returns.
The current executable long and short evaluators use 1:2, subject to valid data/brackets. The UI derives the
displayed ratio from actual entry/stop/target rather than inventing a stock pick.
The entry ledger freezes the corresponding signal's indicator values and check
evidence so a later indicator update cannot rewrite the trade explanation.

The top-three scanner allocation preview uses today's directional entry evidence and default
cost/slippage assumptions for indicative quantities only. The historical
portfolio recalculates each signal and ranking at its own historical time.

The P&L dashboard shows shared-account return, ending capital, drawdown, fees,
maximum concurrent stocks, minimum cash, per-stock realized P&L, daily P&L,
equity/cash curves and downloadable trade/equity data. Entry, exit and signal
times display in IST; daily bars retain a daily-bar label. Exports preserve raw
timestamps with explicit IST columns and spreadsheet formula protection.

Current Nifty constituents and today's scan matches can introduce survivorship
and selection bias. This is not historical index membership reconstruction.
Results remain simulations and do not create paper or live broker orders.

## API and compatibility

`POST /technical/portfolio-backtest` requires the Admin API key. Send symbols,
strategy ID, mode, period, costs and slippage. Account capital, reserve and
position limit are fixed on the server; requests trying to override them or
request paper execution are rejected. The result is saved as one PORTFOLIO run
with the per-stock ledger. The original single-stock research endpoint remains
for compatibility with existing integrations/history, and is not used by the
new shared-account webapp workflow.

For the separate live-paper storage blocker, follow
[M02 activation and recovery](M02_M03_OPERATIONS.md#m02-activation-on-the-existing-render-service).
Neither a backtest nor the scanner's allocation preview can attach a disk or
bypass paper readiness.
