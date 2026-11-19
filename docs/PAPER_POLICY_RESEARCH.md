# Corrected paper-policy research

Calculation registry: `strategy-v12-paper-policy-costs-wilder-adx`.
Approved entry and exit rules remain `approved-horizon-strategies-v1`.

The corrected run captures the resolved, saved paper admission policy before
starting. Its fingerprint includes capital, cash reserve, account and daily
limits, score, confidence, minimum reward/risk, risk sizing and modeled costs.
Historical entries use the same admission function as approved paper entries.
Reports count rejection reasons, including targets that cannot cover modeled
round-trip costs. Changing the saved policy makes its previous admission
evidence stale. Earlier registry evidence cannot qualify for the new registry.

ADX and DI use Wilder smoothing. Indicator history starts before the evaluation
window, with the previous full year available for yearly pivot references.
Trading and returns remain restricted to the requested evaluation window.
Daily entries use an observed 09:30 IST price, with subsequent session ranges;
the 09:15 daily open cannot stand in for an admissible 09:30 entry. Missing
execution prices are rejected. No synthetic bars or quotes are generated.

The cost model uses explicit estimates: 4 bps per fill for intraday, 12 bps per
fill for other horizons, 5 bps adverse slippage and an estimated ₹15.34 delivery
exit charge once per stock per day for overnight delivery exits. These are
research estimates, not a reconstructed historical statutory tax schedule.
Slippage is included in fill prices; net P&L subtracts transaction costs once.
New approved paper positions retain their cost evidence, and partial exits
record net P&L atomically. Legacy unmodeled paper rows remain identified as
legacy; their actual costs cannot be inferred retrospectively.

The independent-stock report remains a diagnostic view. It distinguishes
stocks without trades, traded stocks with zero net P&L, losing stocks and
profitable stocks. Full-universe qualification gates remain unchanged.
Partial exit cash is attributed to its actual exit month.

The shared book uses one ₹100,000 account, at most three open positions and
the captured account limits. All approved executable strategy/horizon pairs
are fixed before the run. Candidate ranking, registry order, universe order
and scan claims match paper automation. Prices are observed on a 15-minute
grid, so polling latency and tick-level execution are not reconstructed.
Intraday scans run once per native bar and daily horizons once per session.
Complete scan coverage is required for admission; missing stocks are reported
as coverage blockers instead of being removed from the requested universe.

The shared comparison uses the common 60-calendar-day interval. Independent
intraday, swing and positional diagnostics use their respective 60-day,
two-year and five-year evaluation windows. Evidence and the frozen cutoff
are checkpointed privately. Replay files use numeric compressed arrays and
bounded caches, and stop before consuming the persistent disk reserve.

Reports → Policy validation displays the separate shared-book and independent
views, the policy and rejection reasons. Reason counts cover every rejection;
the page shows up to 50 stock/time examples per strategy/horizon and the private
JSON export retains up to 100 examples per stock/strategy/horizon. The one-use
`run_corrected_research` operator command starts historical research only.
It never starts paper automation or submits broker orders. Paper forward
testing still requires a separately agreed admission or research policy.

The universe uses current constituents, not point-in-time membership. These
results are neither out-of-sample nor walk-forward evidence. Minimum target
room, cooldowns, the EMA20 trail and VWMA confirmation behavior have not been
optimized or changed to improve the results.

Checkpoint arrays now use lossless compressed JSON, with legacy plain JSON
remaining readable. Recovery copies a journal into compact staging, verifies
every payload, count and metadata field with a length-framed SHA-256 digest
and SQLite integrity checks, then atomically replaces the original. Reports,
replay inputs and the trading book are retained. Full report exports use gzip
with the appropriate HTTP encoding, so clients still receive JSON.

The one-use `recover_corrected_research` command requires the original failed
or interrupted run, unchanged saved policy and scope, and its original recent
cutoff. It compacts journals before reopening the same checkpoint and resumes
only with sufficient disk headroom. The 96 MiB replay reserve remains enabled.
This changes storage encoding only; calculation and policy versions, strategy
rules and recorded economic results remain unchanged. It does not resize the
disk or start paper automation.
