# R72.6 application audit and paper-trading readiness

Reviewed 2026-10-23 against GitHub `main` at
`8582229859445a2883d604647add279d81e3524b`. Its files match the latest
`feature/r726-technical-only-five-tabs` branch. The pending B06/B07/B07a broker
and dependency fixes were integrated locally as `492e2d8` before this audit.

## Preserved application

The five existing top navigation tabs, their order, layout and styling remain:
NIFTY 50 Watchlist, Technical Scanner, Kite Backtesting, Live Paper Trading and
Live Kite Session. Stock Fundamentals and corporate actions remain outside the
active navigation. Technical scans and backtests explicitly use Kite candles
without fundamental gates. This audit does not restore the FinEdge integration
to the user interface or activate real broker orders.

## Findings and corrections

The audit covers active screen/API contracts, quote and account response
integrity, technical scan/backtest errors and candle completion, paper numerical
validation, workbook/CSV exports, and the inherited dependency/security gates.
Focused regression tests accompany the reproduced errors; passing the original
suite alone did not establish that these behaviors were correct.

The original current-version baseline passed 1,744 tests with two existing
skips and no warnings. The SDK-free production environment matches all 64
locked versions and all 18 direct Core/webapp requirements. The unchanged lock
has complete advisory coverage with zero reported vulnerabilities; its recorded
report remains in `docs/security/B07A_DEPENDENCY_AUDIT.json`.

Corrections in this batch:

- Scanner/backtest mode controls update their history choices before the first
  submission. Failed or malformed runs clear old results; a zero profit factor
  remains visible.
- Public watchlist caches include the backend URL. Quote failures preserve
  validated constituents; malformed, boolean and non-finite prices remain
  unavailable rather than destroying the table or fabricating a zero price.
- Kite account responses require verified authentication and valid book shapes.
  A revoked token cannot retain a ready state, and structured credential fields
  are removed before returning account data.
- Technical responses omit raw exception/provider diagnostic text. Trusted local
  validation remains actionable; unexpected provider errors become safe failures.
  All incomplete/future candles are removed, invalid/duplicate timestamps are
  rejected, and stale or out-of-session bars cannot become paper candidates.
  Exchange holidays are handled conservatively without a holiday calendar.
- The frontend normalizes malformed/non-finite JSON and transport/gateway
  failures. Redirects are rejected to prevent forwarding the admin header.
  Existing actionable client errors and the fixed storage-block message remain.
- Paper runtime inputs and marks reject non-finite/boolean values and overflowing
  P&L. State mutations are serialized, failed admission rolls back, and failed
  position recovery blocks entry until successful recovery. Exits, monitoring
  and kill controls remain available. Invalid existing accounting also blocks a
  new fill before saving it. The API rejects malformed NSE symbols.
- Paper P&L labels identify the last saved marks and monitor status. CSV/XLSX
  exports escape formula-like values and headers, validate the daily statement,
  and use its authoritative IST date. Accounting remains simulated and excludes
  fees/slippage.
- Failed portfolio/readiness reads disable new entries without hiding the
  existing emergency controls. Missing data is labelled unavailable and cannot
  become invented zero balances or a downloadable statement.

## Local verification

- **1,932 passed, two existing skips, zero warnings** in the fresh SDK-free
  Python 3.12 environment, including real Streamlit interaction tests.
- Fresh complete advisory audit: **64/64 packages, no skips or advisories**.
- Both scoped strict Pyright projects report zero errors or warnings.
- The exact workflow quality command passes: 26 files pass strict Ruff and
  formatting; active application files also pass scoped Python error checks.
- Compilation, dependency consistency and deployment preflight pass. The
  navigation and application entry-point files match current main exactly.
- An offline production startup opens its port in 1.42 seconds; `/livez`,
  `/app/` and `/production/health` return HTTP 200 with external HTTP requests
  blocked and trading disabled.

Secret scanning covers both the current files and complete reachable history;
the release gate must pass on the committed changes before publishing. Remote
CI and exact Render SHA verification remain separate release requirements.

## Live paper-trading decision

**Production live paper trading is not confirmed ready.** The current supervised
ticket uses a manually entered simulation price and quantity. Its shared entry
boundary enforces enable, kill and storage controls; it does not turn that
ticket into a live-quote fill or apply every automatic strategy-sizing gate.
Automatic strategy admission is a separate path. Neither path is a broker order.

The checked-in free Render service has
`TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION=false` and no verified persistent
disk. Normal production entries therefore remain blocked until storage and
recovery are verified. Enabling disposable simulation would not establish
durable operation. Free-service suspension is also unsuitable for continuous
quote monitoring.

The following evidence is still required before a live paper acceptance claim:

| Gate | Required evidence |
| --- | --- |
| Release | Required CI checks pass and Render serves the exact merged SHA. |
| Kite data | An authenticated read-only session returns valid instruments, current timestamped quotes and completed candles. No secrets appear in browser bundles or logs. |
| Monitoring | The configured quote/exit monitor runs continuously; disabled, failed or stale polling is visible. Successful LTP retrieval alone does not prove exchange timestamp freshness. |
| Admission | Paper is explicitly enabled, kill controls work, and each intended manual/automatic path has reviewed quantity, risk, session and fill rules. |
| Recovery | A real persistent mount preserves trades, open positions, risk accounting and saved kill state across a controlled restart/read-back check. A configured path or local reopen is insufficient. |
| Acceptance | Controlled simulation confirms P&L, stop/target exits, duplicate prevention and recovery using real read-only market data, with no real broker orders. |

The manual ticket also lacks a generic supervised close operation for positions
without strategy lineage. Review that exit workflow and the manual ticket's
risk/fill contract before promoting it to live paper acceptance. The existing
all-or-nothing quote batch also needs operational review: one missing symbol
currently prevents the whole automatic mark batch from advancing.

No production paper position, broker order, paid resource or destructive restart
is created by this audit. Missing evidence remains pending rather than passed.

The preceding five-tab release, `8582229`, passed its existing workflow and exact
Render verification in [run 39831609454](https://github.com/TrendForge2001/TRENDFORGE_CORE/actions/runs/39831609454).
That historical deployment does not include this audit's fixes or the pending
B07a SDK remediation. Its earlier workflow did not include the new advisory and
secret gates. New changes require their own green checks and exact SHA evidence.

## Replacement frontend and hosting

Streamlit is the current UI framework. A replacement requires implementing the
same screens in another frontend; changing the hosting service alone does not
replace it. Keep the five-tab design during that migration.

| Option | Fit for TrendForge |
| --- | --- |
| **Next.js on Vercel, FastAPI on an always-on Render service** | Recommended separation. Build the current tabs in React/TypeScript and keep broker credentials, paper accounting and monitoring on the backend. Use a persistent disk for the existing single-worker SQLite implementation; migrate storage and coordination before adding workers. |
| **Next.js and FastAPI on Railway** | A single hosting provider for frontend, API, long-running monitoring and a persistent volume/database. The same storage and restart acceptance gates still apply. |
| **Next.js and FastAPI on Render** | Keep the existing provider and deploy a separate Node frontend beside the Python API. Use an always-on backend for the monitoring runtime. |

Do not run the paper engine or continuous quote monitor inside frontend
serverless request handlers. A frontend migration is separate from this
correctness audit; no design or tab replacement is included here.
