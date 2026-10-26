# Live-market paper trading controls

This release supplies operator Start/Stop controls for simulated trading. It does
not turn automation on during deployment and does not submit live broker orders.

## Start from a scanner

1. Sign in with the deployed service's webapp and Admin keys.
2. Run one of the four executable source scanners in Technical Scanner.
3. Under **Paper trade scanner candidates**, select up to 100 BUY candidates.
4. Choose **Start paper trading selected stocks**. The server validates membership
   in NIFTY 500, validates the chosen source strategy against that parent universe,
   and re-scans only the selected stocks. Quotes, candles and risk approval are
   checked again before a fill. A previous BUY signal is not a fill instruction.

The handoff is limited to verified NIFTY 500 membership. Stocks outside that
parent universe (including some micro/small-cap constituents) are rejected,
not silently substituted. Full-parent historical validation can take time and
can reject a strategy. The UI displays the actual automation phase and blockers.

## Start/stop in Live Paper Trading

**Start automated paper trading** starts the displayed target scope. The default
is all executable source pairs over NIFTY 100; a previously selected scanner
scope is retained for operator review and resubmitted explicitly on Start.
**Stop automated paper trading** prevents new entries, including in-flight
candidate admission. It remains available when status/readiness reads fail.
Existing positions continue monitoring and exits; Stop does not liquidate them.
The independent paper kill switch remains available for emergency entry blocking.

A Start still validating membership cannot override a newer Stop. Stop automation
before changing an active target scope. Configurations
are saved, but process restart always leaves entries OFF and requires operator
Start again. The backend worker runs independently of an open browser. The
server must remain running throughout market hours.

New entries require the existing durable-storage/restart-verification policy,
paper feature flags, kill switch OFF, a running worker, accepted strategy
validation, risk/capital approval, completed candles, and a fresh Kite quote.
Review-only medium/long-term pairs cannot be selected for automatic entry and
no longer consume background candle scans.

The current entry window is weekdays 09:30–14:45 IST; each strategy's own entry
rules still apply (EMA 9/20 starts after 09:45). Position monitoring is retained
09:15–15:30 IST. Candle and exchange quote checks also prevent stale/non-session
fills. Existing daily/strategy P&L and raw-plus-IST timestamps are preserved.

A free Render instance with unverified ephemeral storage cannot run durable
paper entries. Use the existing documented persistent-storage setup; no paid
resources are provisioned and no storage gate is bypassed by these buttons.

## Kite live-trading preparation

In **Live Kite Session**, **Check Kite trading readiness** makes read-only
session/quote probes. It separates authentication from fresh quotes (quotes can
be stale outside market hours), reports broker opt-in flags as configuration
only, and lists the remaining live-execution work. The admin-protected endpoint
is `/workspace/kite-trading-readiness?probe_quotes=true`.

Current status is preparation-only: the unified webapp has no approved live
order submission workflow. Keep broker writes disabled. Before activation, the
following still need implementation and validation:

- A manual order preview with instrument, quantity, product and price validation.
- Server-side live capital, position, loss and notional limits.
- Explicit operator order confirmation and duplicate-order protection.
- Broker order/fill reconciliation, rejection/cancellation handling and audit logs.
- Supervised acceptance with explicit authorization for actual broker orders.

A valid session or enabled environment flag alone never makes this readiness
report approve an order. The checks never place, modify, cancel or queue orders.
