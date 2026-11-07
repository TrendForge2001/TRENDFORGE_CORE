# Trendforge project status — 7 November 2026

Trendforge is at **paper-automation validation**. Research, scanning, historical
simulation, paper execution and reporting exist. Positive account-level results
after costs and readiness for live capital have not been established.

The integration starts from main commit
`2a47cb6bd6cf65835108184818cf9e17f6f40c47`, preserving the latest EMA/pivot,
staged-entry, history-alignment and bounded NIFTY scan work. The catalog has
**19 strategies: 17 executable definitions and two review-only definitions**.
Implemented strategies still require current validation and runtime/risk gates.

## Runtime decision

The original <https://trendforge-core.onrender.com/app/> is the canonical
read-only cloud workspace. The Windows PC is the primary paper-execution runtime.
No paid Render disk or automatic PC-book synchronization is planned. The local
ledger is `<DataRoot>/database/trendforge.db`; default DataRoot is
`%LOCALAPPDATA%\TrendForgeCore`.

Both older local SQLite books have separate audit-follow-up backups. They have
different schemas and were not merged, replaced or deleted. Identify the
authoritative existing book before moving it into the PC runtime.
See [cloud/PC operations](CORE_CLOUD_PC_OPERATIONS.md).

## Audit follow-up

| Finding | Status and next action |
|---|---|
| F03 — ADX tie bug | Fixed: both DM masks compare original movements. Fixtures cover ties, flat prices, warm-up, direction and hand-calculated values. |
| Validation identity | Calculation `rolling-v2-adx-dm-ties`; registry `ema-pivot-staged-paper-v6-adx-dm-ties`. Paper promotion requires current-registry validation. Existing positions retain exit controls. |
| F17 — environment | Clean Python 3.12 environment installed from production/test/security requirements, including httpx2, detect-secrets, Ruff, Pyright and pip-audit. **2,412 passed, four skipped**. A real Windows fixed-drive check is among the skips and must run on Windows. |
| Security checks | Dependency audit covered **68/68** locked packages with no reported vulnerabilities at verification time. Offline secret scanning passed current files and complete reachable Git history. Scoped Ruff and both strict Pyright projects passed with no type errors; requests-source discovery warnings remain in the cloud environment. These checks do not prove absence of vulnerabilities. |
| Kite credentials | Shared settings/runtime resolution, whitespace/BOM handling and Render `kite.env` fallback. Complete process credentials win. A read-only startup profile probe records fixed authentication codes without account data or credentials. Saved values need a fresh deploy/process; broker acceptance must be verified there. |
| Execution placement | Explicit cloud role blocks manual paper entries and automation starts. PC launcher clears the role and keeps real orders disabled. Cloud screens explain that they do not read the PC book. |
| Presentation | Navy backgrounds, brighter text, selected navigation/tabs, green Start, red Stop/kill, amber release, visible focus and disabled states. Both Streamlit launch configurations share the palette. |
| F13/F14 | Removed unused trade_executor, root backtesting_engine/optimizer and three empty JSONs. Active services and valid alerts configuration retained. |
| F04 — smoothing | Compare existing rolling RSI/ATR/ADX conventions against actual Kite/TradingView chart settings. No unverified Wilder switch. |
| F05/F06 — risk | Owner requested full-capital historical backtests: three positions, ₹100,000 initial capital/deployment ceiling and ₹0 fixed reserve. Existing stop-risk limits and paper controls remain. Account-wide daily-entry and realized-plus-open-loss rules still need acceptance across backtest/paper. |
| F09/F10 — runtime/book | Runtime chosen. Actual PC installation, authoritative-book selection, restart/restore, data freshness and unattended exit-monitor acceptance remain. |
| F07/F08 — strategy evidence | Corrected-version holdouts and forward paper evidence required. Judge the shared account after costs, correlation and selection bias. Earlier audited books had no saved strategy-result evidence. |
| F01/F02 — live lifecycle/protection | Deliberately deferred until paper evidence is positive net of costs and within approved risk limits. Real broker orders disabled. |
| Review-only EMA 50/100 and 100/200 | Remain excluded from executable promotion. |
| F15/F16 — broad docs/API split | Deferred behind risk, data and runtime acceptance. |

## Completion sequence

1. Land ADX/current-validation fixes, clean tests and early deletions.
2. Confirm smoothing, seeding and warm-up against the chart used for decisions.
3. Approve/enforce one account-risk policy across portfolio backtests and paper.
4. Verify PC ledger, token/profile/quotes, calendar, data coverage, restart,
   backups and exit monitors. Render remains read-only.
5. Begin at least 20 complete forward paper sessions once steps 2–4 pass.
   Measure account-level net expectancy, drawdown and correlated exposure.
   Twenty days alone is not a promotion criterion and may provide too few trades.
6. Decide whether the measured edge justifies live lifecycle/protective-exit work.

## Verification boundaries

Detailed release commands/reports are retained separately in
`TRENDFORGE_RELEASE_2026-11-07/evidence`. Earlier audit results apply to their
original revision. Deployment status, current Kite authentication, browser
evidence and exact release SHA are recorded in the release handoff after deploy.
A test pass does not certify a running PC, fresh exchange quotes or profitability.
