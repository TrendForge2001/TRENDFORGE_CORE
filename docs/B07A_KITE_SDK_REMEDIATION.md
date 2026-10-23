# B07a — Kite SDK dependency remediation

## Implementation and dependency evidence

TrendForge now uses a first-party client for its existing Kite REST operations
and a market-data streaming adapter on `websockets`. The vendor SDK is removed
from Core requirements and the production lock. The latest published SDK is
still 5.2.2 and still pins Autobahn 19.11.2; its exact dependency requirement was
not overridden. No vulnerability exception or suppression was added.

The resolver-derived lock drops from 76 to 64 packages. Surviving versions are
unchanged. Removed packages are KiteConnect, Autobahn, Twisted, Automat,
constantly, cryptography, hyperlink, Incremental, pyOpenSSL, service-identity,
txaio and zope.interface. Dependencies still required by other components remain.
`websockets>=17.2,<18` is now direct; version 17.2 was already in the lock.

A fresh installation passes `pip check` and exact-version verification. The
live PyPI vulnerability audit passes with **64/64 packages, zero skipped packages
and zero reported advisories**. The [recorded sanitized report](security/B07A_DEPENDENCY_AUDIT.json)
binds that result to the committed lock digest. The old [B07 report](security/B07_DEPENDENCY_AUDIT.json)
is retained as historical evidence.

This removes the affected SDK dependency tree from the deployed application
graph. B07b's wait for a patched Twisted release is no longer needed for this
graph; Twisted itself was not patched by this project.

## Preserved REST and execution contracts

`KiteProvider`, legacy `KiteService` and the local observer use the new transport.
Authentication environment settings, login URL, session checksum/exchange and
token invalidation retain their existing contract. Existing account, holdings,
positions, orders, trades, quotes, instrument CSV, candles and GTT reads remain
available. CSV numeric/date normalization, quote/order timestamps and candle
timezone/OI output are covered with fake responses.

Only the subset used by TrendForge is implemented; this is not a general SDK
replacement for external extensions. A fresh-process test blocks SDK imports
and network access while importing every broker integration. Architectural tests
also reject retired SDK imports and production requirements.

Live execution keeps B06's captured-instance plus runtime-environment gates.
Wrapper client access remains guarded. The REST transport additionally denies
mutations without an explicitly supplied execution-policy callback. Place,
modify and cancel make one HTTP attempt. Real injected Requests sessions have
Kite-origin retry adapters replaced and TLS verification enabled. Redirects are
rejected; response and transport exception text are not copied into errors.
Non-finite JSON numbers, malformed data and invalid resource identifiers fail
before becoming market data or alternate endpoint requests.

Aware datetime request inputs retain the old SDK's wall-clock formatting
behavior. That compatibility does not perform a timezone conversion. Runtime
admission checks cannot retract a request already sent to the broker and are
not a distributed execution lock.

## Streaming compatibility

The legacy WebSocket service has no production composition or route caller in
the audited source, but its public service interface is preserved. The new
adapter handles subscriptions, modes, cached ticks and callbacks, with strict
8/28/32/44/184-byte packet decoding, exchange price divisors, OHLC, volume, OI,
timestamps and market depth. It uses the fixed Kite TLS origin, rejects redirects,
suppresses credential-bearing library diagnostics and bounds reconnect attempts.
No streaming message can submit a broker order.

Protocol behavior was checked against the installed SDK 5.2.2 implementation;
official documentation URLs were unavailable from this workspace. Relevant
MIT attribution is retained in [third-party notices](../THIRD_PARTY_NOTICES.md).
Tests use generated credentials, fake HTTP sessions, fake sockets and packed
binary fixtures. Local tests submit no authenticated broker request or real order.

Socket shutdown detaches connection state before aborting transport I/O, and
subscription operations preserve intent and wire ordering independently of that
state lock. Network timeouts do not preempt the operating system's DNS resolver;
an opening resolver thread can outlast shutdown's bounded join. Module import
and client construction remain offline.

## Local validation

The fresh SDK-free Python 3.12 environment passed **1,738 tests, with two skipped
and no warnings**. This includes 76 fake-HTTP transport tests, 35 streaming/service
tests and three architecture checks. Compilation, dependency consistency, exact
installed-version verification, deployment preflight, scoped Ruff and both strict
Pyright projects passed. The complete advisory scan and reviewed secret scan
also passed. These are local results; authenticated broker acceptance remains
separate.

## Release and acceptance

Remote Python 3.11/3.12, locked-production, quality and security checks must pass
on the release commit before main is updated. B06/B07 were previously held on
release branches because Actions runs did not register and manual API dispatch
was blocked. The delayed [B07 run](https://github.com/TrendForge2001/TRENDFORGE_CORE/actions/runs/39822586404)
is now available: regression, quality and secret checks passed; the vulnerability
job was the sole failure. The new release commit still needs its own checks.
Local success alone does not establish a green remote release.

After those checks, merge and verify that Render serves the exact merged SHA.
B08 must still validate an authenticated read-only session, instrument/candle
data, browser navigation and any intended streaming usage. Real cloud storage
recovery remains a separate acceptance gate.
