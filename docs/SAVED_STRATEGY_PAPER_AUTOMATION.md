# Saved-strategy live paper automation

The existing five tabs and design remain. **Live Paper Trading** gains an
operator ON/OFF switch, status and blockers, and daily/weekly/monthly/yearly/all
statements for every saved strategy. Each statement includes closed trades,
current open positions, realized P&L, unrealized P&L and Excel exports for either
one strategy or the whole catalog. Zero-trade strategies remain visible.

## Execution contract

- The backend runs independently of an open browser and polls every 15 seconds.
  The paper tab refreshes its automation/status section every 15 seconds.
- All 19 registered strategies are considered on NIFTY 100, across their declared
  intraday/swing/positional modes. Missing complete-catalog validation is started
  in the existing background validation runtime. Failed or insufficient gates
  remain blocked; confirmation-only/review-required rules are never promoted
  into executable entries. The paper bridge currently supports intraday and
  swing; positional evaluations show `paper_mode_not_supported`.
- Intraday scans run once per completed 15-minute slot; daily modes once per IST
  day. Execution claims are persisted before work, including failures, to avoid
  repeating uncertain operations. Latest outcomes remain visible between scans.
- New entries run weekdays 09:30–14:45 IST, using completed current Kite candles
  and timestamped Kite quotes no older than 60 seconds (at most 5 seconds ahead).
  A simulated fill uses the current quote; sizing and reward/risk are rechecked.
  Missing/stale data stops entries. There is no real broker order submission.
- Strategies share existing portfolio capital, position limits, daily loss rules,
  kill controls and the one-position-per-symbol policy. This is not an independent
  virtual capital allocation for each strategy. Duplicate-symbol and risk blocks
  are visible in cycle outcomes.
- OFF invalidates in-flight entry admission under the same lock as paper fills.
  Existing strategy positions continue fresh-quote stop/target monitoring during
  market hours and strategy exit checks every 15 minutes. The legacy technical
  auto-scanner remains research-only; automatic entries use this switch.
- A restart always leaves automation OFF. A saved ON preference produces a
  resume-required notice. Restored positions can still be monitored.
- Statements use the exit date in IST for realized P&L (legacy missing exit dates
  use their entry date). Open P&L is the latest stored mark, not a period return.
  Fees and slippage are excluded. Invalid accounting fails instead of displaying
  invented zeroes. Spreadsheet text is escaped against formulas.

For PC disk operation or the storage warning, follow [the storage setup](PAPER_STORAGE_SETUP.md).

## Durable operation on Render

The current `render.yaml` selects a **free** web service. A sleeping free service
cannot provide continuous market monitoring or a persistent disk. Provision an
always-on backend with an attached persistent disk before activating automation.
This change does not create a paid resource or attest recovery on your behalf.
Use one Uvicorn worker and one backend instance with the current SQLite book.

Configure the disk and environment, for example:

```text
TRENDFORGE_DATA_DIR=/var/data/trendforge
DATABASE_PATH=/var/data/trendforge/database/trendforge.db
TRENDFORGE_PERSISTENT_MOUNT=/var/data
TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION=false
TRENDFORGE_PAPER_TRADING_ENABLED=true
TRENDFORGE_PAPER_AUTO_ENTRY_ENABLED=true
TRENDFORGE_PAPER_TRADING_KILL_SWITCH=false
WEB_CONCURRENCY=1
```

Keep `TRENDFORGE_ADMIN_API_KEY` and Kite credentials in server secret settings.
The existing manual Kite access token must be current for the session. Existing
capital/risk configuration remains effective.

Before setting `TRENDFORGE_STORAGE_RECOVERY_VERIFIED=true`, verify the actual
mount, back up the SQLite database, perform a controlled restart, and confirm
settings, execution claims, ledger and positions recover from the same database.
Check `/paper/readiness` for durable storage and successful position restoration.
Do not set the recovery flag merely to remove the warning.

Use the authenticated `/paper/automation` status endpoint, or the existing paper
tab, to review blockers. Apply ON when readiness is satisfied. All three new
endpoints require `X-TrendForge-Admin-Key`:

| Endpoint | Purpose |
| --- | --- |
| `GET /paper/automation` | Worker state, blockers, strategy catalog and latest cycle |
| `PUT /paper/automation` with `{"enabled": true/false}` | Persist operator intent and change entry admission |
| `GET /paper/strategy-pnl?period=daily` | Full strategy statements from the canonical paper ledger |

A green offline suite verifies simulated behavior. Live readiness still requires
an always-on process, verified disk/recovery, a current Kite session, completed
validation and an observed market-session scan/entry/exit/restart exercise.

## Verification for this change

Offline suite: **1,975 passed, 2 existing skips**. Focused automation tests cover
OFF during a blocked quote request, restart OFF behavior, all-strategy scheduling,
persisted claims, storage/kill/time gates, fresh quotes, full ledgers exceeding
1,000 trades, zero-trade statements, Excel formula escaping, authenticated API
controls and paper-tab interactions. Production dependency audit covered all
64 locked packages without an advisory. Scoped lint/format, both existing strict
type checks, dependency consistency and deployment preflight passed.

An actual local unified Uvicorn runtime bound in 1.22 seconds with external HTTP
blocked, served `/livez` and `/app/`, and returned authenticated automation and
strategy P&L responses. The worker was running OFF and all 19 empty statements
were present. These checks do not establish production disk durability or a
successful live-market session.
