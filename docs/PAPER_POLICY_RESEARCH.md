# Corrected paper-policy research

Calculation registry: `strategy-v12-paper-policy-costs-wilder-adx`.
Approved entry and exit rules remain `approved-horizon-strategies-v1`.

## Explicit research forward paper admission

`paper-research-admission-v1` is a separate, owner-started forward-paper policy.
It preserves historical FAIL/INSUFFICIENT verdicts; it does not qualify a strategy
for live execution. Validated mode retains its historical PASS and complete-scan
requirements. Research mode covers approved LONG entries only, across their
registered horizons, using the saved BUY-only account policy. Bearish exits and
approved trade-management rules remain unchanged.

Research requires completed evidence for the current registry, universe and
saved account-policy hash. Each fill checks the captured scope and policy again.
A completed or degraded scan must account for every requested stock and have at
least 90% successful coverage. Failed stocks cannot enter, and each candidate
still requires its own completed signal candle, a fresh Kite quote and all
existing cost, reward/risk, exposure, loss and entry-window checks. Missing stocks
remain visible in coverage; the requested universe is not silently reduced.

Research uses the canonical shared paper account, without resetting its ledger.
`admission_mode` and `research_policy_id` persist through open-position recovery,
partial exits and statements; reports provide separate research counts and P&L.
Historical simulation output is unchanged. No broker order path is enabled.

The authenticated automation control accepts `admission_mode: "research"` when
starting. The expiring, durably claimed `start_research_paper` operator request
performs operational preflight and issues Start once, without rerunning history.
It requires sole-Render-executor confirmation and waits for the market entry
window and fresh data. Stop invalidates pending admission; ordinary restarts
leave entries OFF while exit monitoring continues.

## Historical simulation contract

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
