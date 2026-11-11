# Render paper host and bounded research

Owner decision: Render is the paper execution host; stop the PC executor before
pressing Start on Render. The cloud session cannot inspect or stop that PC.
The Render book is separate; PC trades and reports are not imported or merged.

Canonical mobile browser page:
<https://trendforge-core.onrender.com/app/paper_session>.
Sign in using only the webapp access key. API authentication stays in the
server environment. The page requires explicit
confirmation that the PC executor is stopped and the intended book is Render.
Start/Stop and emergency kill controls operate on the server. Closing a mobile
browser does not stop its backend. A server restart always resets automation OFF.

## Deployment configuration

The existing Dashboard-managed service, single instance, paid compute and disk
remain authoritative. Keep the existing database and recovery proof. Set
`TRENDFORGE_CLOUD_PAPER_EXECUTION=true` to opt in to the new startup bootstrap.
It validates the mounted existing database and two-boot recovery evidence, holds
an exclusive book lock, applies the existing shared paper policy and forces real
broker writes OFF. Missing or mismatched storage evidence blocks startup rather
than initializing a new book. The standard `uvicorn start:app` entrypoint stays.
Keep `WEB_CONCURRENCY=1`; the lock rejects multiple server workers.

Paper policy: ₹100,000 starting capital, zero fixed reserve, three open positions,
six new entries per IST day, daily loss based on realized plus open losses at 3%
with the existing realized-loss guard. Existing per-trade risk and sizing limits
remain. Paper statements exclude simulated costs/slippage; historical backtests
include them. Backtest/paper allocation parity remains a separate open item.

## Sequential research

On Render, stock lists and optional same-horizon strategy groups split into
independent accounts: at most 50 stocks and a 50,000 observed-candle budget per
child, with planning headroom. One worker executes children sequentially in
isolated subprocesses; the three-request queue and 30-minute child timeout remain.
At most 256 children form one campaign. Unexpected observed history over budget
fails that child explicitly; it does not silently drop stocks.

Each child saves its entry/exit or scanner report. The parent saves a compact
CSV/Excel index only when all children complete. Child results are independent
portfolios, not summed full-universe P&L. Cancel stops current/future children;
already completed child reports remain available. Restart does not replay work.
Heavy research cannot start while paper automation/validation is active, and
paper Start/validation wait until admitted research finishes or is cancelled.
Stop and emergency controls remain available during failed/slow Start attempts.

The backtesting-period dropdown and two primary Scan/Backtest actions remain.

## Kite and timestamps

Kite preparation includes authenticated session/history/quote checks and a
read-only quote-based order preview. Preview checks the current NSE equity
instrument, tick/lot, fresh quote and protective-level direction. It cannot place
orders; live-money risk admission, confirmation/duplicate control, reconciliation
and protective-order lifecycle remain pending. Do not enable real broker orders.

Binary exchange epochs now decode directly to aware Asia/Kolkata timestamps,
independent of the Render host timezone. REST history uses explicit IST request
windows. Exchange quote/bar timestamps remain distinct from server event clocks;
daily candle dates do not establish intrabar fill times.

## Acceptance boundary

Release CI verifies synthetic research at the actual paid plan's 0.5 CPU/512 MiB,
restart/archive recovery,
390×844 mobile sign-in/Start/Stop/kill controls and no broker clients in those
fixtures. Deployment checks verify exact SHA, public UI/liveness and actual disk
recovery. These checks do not establish fresh in-session quotes, completion of
the owner's full current-catalog validation, or successful real-market paper
fills. Current daily Kite authentication and all existing readiness gates must
pass before entries. Never bypass a gate to show an active status.
