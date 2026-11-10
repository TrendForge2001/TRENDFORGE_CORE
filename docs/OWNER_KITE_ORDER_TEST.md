# Owner-authorized pre-open order test

This is a separate one-shot operator request, not strategy automation or a
general order ticket. The owner explicitly authorized NSE SBIN BUY 5 shares,
CNC, MARKET, accepting possible execution or queueing. The request uses regular
variety and DAY validity. No AMO, limit, sell, cancellation or retry fallback is
authorized by this mechanism.

`TRENDFORGE_OWNER_KITE_ORDER_TEST` is absent/empty by default. An operator can
configure a JSON intent with `intent_id`, `symbol` (SBIN only), `quantity` (5 only),
`accept_execution: true` and a timezone-aware `expires_at`, no later than 09:15
IST on the current date. Startup runs it only on the verified persistent Render
book. The normal broker-write and automated-live-trading flags remain OFF.

The worker reserves the immutable intent in the existing SQLite settings table
before network activity. It verifies current authentication and the NSE equity
lot, persists the submission reservation, and permits one exact order POST on a
private scoped REST client. Repeated boots or concurrent workers cannot submit
the same intent twice. Expiry is checked again immediately before submission.
A transport failure has an unknown outcome: query the tagged broker order and
never automatically retry the POST. A crash retains its durable reservation.

The result logs only this request's receipt and selected broker status/fill
counts, with no credentials or other account orders. A returned order ID is an
acknowledgement, not proof of a fill. A closed market can still accept or queue
an order. The owner must monitor any accepted request in Kite. After the attempt,
clear the operator intent; retain the durable receipt and general live lock.

No broker request runs in release tests. Tests cover exact order fields, disabled
defaults, rejected inputs, authentication failure, broker rejection, timeout,
concurrency, restart duplicate prevention and missing-book protection.
