# Owner-authorized single order test

This is a separate one-shot operator request, not strategy automation or a
general order ticket. The owner explicitly authorized NSE SBIN BUY 5 shares,
CNC, MARKET, accepting possible execution or queueing. After the regular request
was rejected with HTTP 403, the owner separately requested an AMO on the verified
10 November 2026 market holiday. The variety must be explicitly selected; an AMO
never follows a regular rejection automatically. Both use DAY validity and
Kite's documented automatic market protection (`market_protection=-1`). No limit,
sell, cancellation or retry fallback is authorized by this mechanism.

`TRENDFORGE_OWNER_KITE_ORDER_TEST` is absent/empty by default. An operator can
configure a JSON intent with `intent_id`, `symbol` (SBIN only), `quantity` (5 only),
`accept_execution: true`, `variety` (`regular` or `amo`) and a timezone-aware
`expires_at`. Regular tests expire by 09:15 IST today; an AMO test must expire
today and within one hour. Expiry limits submission only: an accepted AMO can
remain queued for the next trading session. Startup runs only on the verified Render
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

Primary references: [Kite order API](https://kite.trade/docs/connect/v3/orders/),
[Zerodha AMO support](https://support.zerodha.com/category/trading-and-markets/charts-and-orders/order/articles/auto-amo),
[2026 holiday calendar](https://zerodha.com/marketintel/holiday-calendar/).
