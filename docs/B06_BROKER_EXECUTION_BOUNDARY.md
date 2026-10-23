# B06 — Broker execution boundary

## Scope and execution policy

`KiteProvider` and the legacy `KiteService` share one live-execution guard.
Placing, modifying and cancelling orders require both an instance initialized
with live trading enabled and a current affirmative
`TRENDFORGE_LIVE_TRADING_ENABLED` environment value. The default remains false.
Missing or unrecognized values deny writes. Removing the environment opt-in
denies subsequent calls on existing instances, including saved public client
method references. Enabling the environment alone does not activate an instance
initialized with execution disabled.

The guard runs before client access and again immediately before each SDK
mutation. Public `provider.kite` and `service.client` accessors return a guarded
facade. Existing market/account reads and authentication methods remain
available; unsupported SDK operations and private HTTP helpers are not exposed.
New mutation features, including GTT creation or position conversion, require
an explicit reviewed integration rather than automatic SDK delegation.

Every order operation has one SDK attempt. A network error can follow broker
acceptance, so callers must reconcile order state before deciding what to do.
The legacy retry helper accepts only this client's quote, LTP and historical
reads, with one to three attempts. The provider's retry helper accepts those
three read names instead of arbitrary callables.

## Emergency operations and caller audit

Cancellation and all legacy buy/sell/limit/exit aliases use the same gate.
Cancellation can remove a protective order. The legacy `exit_position` helper
submits a SELL without establishing the current net position, so it is not a
verified risk-reducing operation and receives no disabled-mode exception.
Operators retain the broker console for intervention. Paper monitoring, exits
and kill controls are separate and retain their existing behavior.

The source audit found no HTTP broker-order mutation route or production caller
of `KiteService`. The execution order manager builds order descriptions; paper
and backtest execution simulate trades. The local runtime's separate raw SDK
client performs profile authentication only. The guarded facade addresses
accidental use through the public wrappers; trusted Python code with access to
private objects or newly constructed SDK clients is outside that boundary.

These checks are process-local admission checks. They cannot retract a request
already sent to the broker or provide coordinated multi-worker shutdown.
Disconnecting or replacing a client does not revoke previously retained session
references; remove the runtime execution opt-in to deny subsequent writes.
This batch does not activate live trading or introduce new broker write routes.

## Validation

Local Python 3.12 full suite: **1,578 passed, 2 skipped**, including 139 new
broker-boundary cases. Compilation, dependency consistency, deployment preflight,
new-file Ruff checks and whitespace checks passed. The existing test-client
deprecation remains scheduled for B07.

Fake broker regression tests exercise both wrappers, default denial, instance
and runtime opt-in, runtime revocation, argument/result forwarding, single-attempt
failure, legacy aliases, disconnected denial, public client access, read retries
and read availability while execution is disabled. They do not submit real orders.

Release checks run Python 3.11/3.12 and the exact production lock, then verify the
merged Render SHA and HTTP 200 from `/livez`, `/app/` and `/production/health`.
