# Strategy improvement experiments

The owner's three recommendations are research hypotheses, not demonstrated
improvements. The release retains versioned production rules. This document
defines the next comparisons; it does not claim they have been backtested.

| Hypothesis | Candidate comparison | Required evidence |
|---|---|---|
| Reduce intraday turnover | Baseline versus higher score floors; separately test daily EMA direction agreement | Account-level net expectancy, trade count, drawdown, missed winners and turnover reduction on held-out dates |
| Improve intraday exits before 15:00 IST | Baseline versus ATR target multiples 1.2/1.5/2.0; separately test a defined morning time-decay/trailing rule | Current risk multiplier audit; exit-reason counts, net P&L, win size/loss size, costs and adverse same-bar ordering |
| Swing/positional emphasis | Baseline swing and daily EMA/pivot 100/200; separately compare fixed and trailing stops | Adequate warm-up plus full requested common history, sufficient trades, holdouts, realistic costs and valid product/borrow assumptions |

Change one dimension at a time initially, freeze the candidate grids before
looking at holdout results, and compare all candidates over the same universe,
dates, capital/risk policy and costs. A reduction of 60–70% in trade count is a
measurement target, not a guaranteed fee saving or profit improvement: filtering
can remove profitable trades too. A smaller target changes reward/risk and can
reduce expectancy even if more targets are hit. ATR target and stop multipliers
must be distinguished from reward/risk multiples before applying overrides.
The standard intraday source-rule bracket currently uses a 1.5 ATR stop and
2R target (approximately 3 ATR), not a 2 ATR target. A 1.2–1.5 ATR target with
that same stop implies only 0.8–1R before costs, below the present paper minimum
of 2R. Such a comparison needs explicitly versioned research rules and cannot
silently change the approved paper admission policy.

Use only completed daily candles when evaluating an intraday daily-trend filter;
the current unfinished daily close would introduce look-ahead in backtests.
Next-bar execution, tick/lot constraints, intraday cut-offs, partial exits and
ambiguous-bar conservative handling must remain consistent across comparisons.

The three supplied workbooks do not retain all per-entry score and daily trend
inputs needed to calculate these alternatives retrospectively. Re-run against
the underlying candle data and version the calculation/strategy identity so
existing validation cannot approve altered rules.

The EMA9/26 bearish-pivot report requested two years but used 103 daily bars and
lost ₹280.10 after fees. It does not establish swing superiority. The mentioned
EMA100/200 bullish setup is not one of these three supplied reports. Assess it
separately, with enough historical warm-up for the 200-period EMA and applicable
entry rules. Historical multi-day cash shorts assume borrow; do not infer broker
product availability from a simulated SHORT label.

Finally compare selected strategies together in one shared account. Sequential
Render stock partitions are independent portfolios and cannot establish a
combined account-level edge by summing their metrics. Forward paper results
remain necessary before considering real broker-order activation.
