# Trendforge project status — 10 November 2026

Trendforge is at paper-automation validation. Research, scanning, historical
simulation, paper controls and reporting exist. A profitable account-level edge
and readiness for real capital have not been established.

The owner's latest choice supersedes the earlier PC-only arrangement: **Render
is the paper host; stop the PC executor before activation.** Real broker orders
remain disabled. The existing cloud book is retained separately from the PC.
See [Render market preparation](RENDER_MARKET_PREPARATION.md).

## Current change set

| Area | Implementation | Acceptance remaining |
|---|---|---|
| Render paper | Explicit cloud startup opt-in, exclusive book lock, existing mounted-book recovery, shared paper policy, restart OFF | Exact deployed revision and storage verification; owner confirms PC stopped |
| Mobile controls | Existing protected browser URL, explicit Render-book confirmation, Start/Stop and kill controls | Release mobile browser acceptance; current in-market readiness/fills |
| Research | Sequential stock/strategy child batches, conservative candle budget, isolated workers, compact independent-account index, cancellation | Release resource-limited browser acceptance |
| Scanner errors | Safe error details retained in new exports; legacy fallback; protected current-input checks | Actual current broker inputs for failed symbols; no invented original diagnostics |
| Market time | Explicit IST binary epoch decoding; earlier IST REST history fixes retained | Release regression checks; actual in-session freshness |
| Kite | Read-only authenticated readiness and quote-based order preview | Live-money risk admission, confirmations, duplicate control, reconciliation and protective orders remain unimplemented; real orders OFF |
| Supplied backtests | All three reviewed and arithmetic checked | None demonstrates positive net edge; swing sample is 103 bars, not two full years |

See [the three-workbook review](BACKTEST_REVIEW_2026-11-10.md). The two intraday
runs lost approximately 21% each after costs. Their results must not be summed
with each other or with the swing run as one shared account.

## Audit follow-up

- F03 ADX tie fix and fixtures remain implemented. Calculation identity is
  `rolling-v2-adx-dm-ties`; current strategy registry is
  `ema-pivot-staged-paper-v7-ist-history`.
- F17 clean pinned test/security environment remains established. Previous
  deployed base b9ff6dfe51a1 passed 2,524 tests with four skips and nine CI jobs.
  Those numbers do not certify the current unmerged change set.
- F04 chart smoothing/seeding parity remains unverified; no unverified Wilder
  switch was made.
- F05/F06 paper policy is ₹100,000, zero fixed reserve, three concurrent
  positions, six daily entries and 3% daily realized-plus-open-loss threshold,
  retaining the existing realized-loss guard. Backtest/paper sizing parity
  remains an open audit item.
- F09/F10 Render has paid single-instance compute and a 1 GB persistent disk at
  /var/data. The configured existing database is retained. PC execution must be
  stopped by its owner; this cloud session cannot inspect it.
- F07/F08 require current-catalog validation, adequate common history, holdouts
  and forward account-level results net of costs and correlated exposure.
- F01/F02 real-order lifecycle and protective-order builds remain deferred.
  Preparation and preview do not approve or place real orders.
- F13/F14 obsolete files were removed in prior releases. Review-only legacy
  EMA50/100 and EMA100/200 stay excluded; daily EMA/pivot counterparts remain.
- F15/F16 broad documentation/API refactors remain deferred behind risk/data work.

No paper-start or successful live-market fill is claimed by this source status.
CI, deployment and actual readiness evidence must identify the exact revision.
