# Paper and live execution requirements — 9 November 2026

The cloud website is https://trendforge-core.onrender.com/app/ and remains
read-only. The selected execution runtime is the owner's PC, whose local app
uses http://127.0.0.1:10000/app/. The public Render website currently has no
authenticated command bridge to the PC. Its health does not establish PC
automation or broker execution readiness.

## Current evidence

The owner reports that the PC installation, fixed-drive recovery, Kite login,
fresh quotes and monitors pass. The original release has no verified paper fills.
At 12:18 IST, full validation had processed 29 of 1,503 symbol/mode units. Each
unit can run several strategies; the counter is not a count of individual rules.
The previous completed validation has an obsolete strategy catalog.

| Requirement | Current status / acceptance evidence |
| --- | --- |
| Durable PC ledger and report recovery | Owner reports passed; preserve existing DataRoot, keys and proofs during repair. |
| Current Kite credentials and exchange quotes | Owner reports passed; recheck after restart and token renewal. |
| Correct history request clock | This repair generates IST windows and converts aware inputs into IST before wire formatting. Same-day, naive/IST compatibility and midnight rollover regressions pass. Live PC verification remains required. |
| Complete prior sessions for pivots | This repair recovers a missing quarter-hour only from all three complete, finite, valid observed Kite 5-minute bars. It preserves original candles and records provenance. If recovery fails, the original gap and invalid pivots remain blocked. Verify against actual PC broker data; the upstream missing-bar cause is still under investigation. |
| Current full-universe validation | Pending. Discard promotion evidence generated with incorrect data. Restart after the repair; retain coverage, cost and profitability requirements. |
| Validation throughput | This repair removes per-candle DataFrame reconstruction for built-in evaluators and preserves the custom-engine interface. Complete trade/equity/metric parity passes across the affected active strategy/mode pairs. |
| Explicit paper Start and entry controls | Implemented; verify locally after data and validation gates pass. Restart leaves entries OFF. |
| Paper entry, exit and saved statement | Pending genuine matching signal and observed local ledger/report evidence. ON alone is insufficient. |

The reviewed paper account uses INR 100,000, zero fixed reserve, three concurrent
positions and six new entries per IST day across strategies. Its 3% entry-loss
guard includes realized and open marked P&L, with a gross realized-loss guard
retained. Risk and capital-per-trade caps still apply. Paper P&L excludes costs
and slippage; validation includes its configured costs. These are separate
accounting conventions and do not establish equivalent account returns.

The history repair advances the validation registry to
`ema-pivot-staged-paper-v7-ist-history`. Older promotions must not approve entries
under the corrected data convention. Stop the old validation before updating the
PC backend and run fresh full-universe validation after the data checks pass.

A three-repeat synthetic benchmark of one 1,125-bar strategy measured median
runtime 1.355 seconds on the original public evaluator and 0.152 seconds after
optimization (8.89 times faster), with identical trades, equity and metrics.
This is a cloud CPU measurement, not a full-PC validation ETA.

## Real broker automation build and acceptance

Real-money settings require their own reviewed allocation, product, permitted
strategies, quantity/risk caps, daily entry/loss limits and activation scope.
Paper account defaults do not approve a real-money allocation.

1. **Broker connectivity and runtime:** current Kite authorization, a registered
   outbound static IP for API orders, and a running durable execution host.
   Quote access does not demonstrate order-placement eligibility.
2. **Admission and operator controls:** instrument/product/tick/quantity checks,
   fresh market inputs, broker funds and positions, shared account risk rules,
   recorded order preview/intention, and explicit approval of the automation
   session and its strategy/risk scope. Provide Stop and kill controls.
3. **Durable order lifecycle:** write an intent before sending it; use stable
   intent IDs and broker tags, serialize admission, and prevent duplicate
   submissions across callbacks and restarts. A timeout is an unknown outcome,
   requiring reconciliation before another submission.
4. **Fills and protective exits:** handle rejection, cancellation and partial
   fills; reconcile actual filled quantities; maintain broker-held protective
   orders; resolve exit races and orphan protective orders without reversing
   the intended position. Paper marks cannot substitute for broker fills.
5. **Recovery and accounting:** reconcile broker orders, trades and positions
   after restart or disconnection before admitting entries. Maintain a broker
   execution ledger separate from simulated trades and produce trade-wise
   reports with actual entry/exit fills and charges.
6. **Acceptance:** automated fault tests for timeouts, duplicates, partial fills,
   rejection, protection failure and restart, followed by supervised broker
   acceptance under the approved real-money policy. Broker writes remain
   disabled until those prerequisites and the execution workflow are verified.

The existing release exposes a read-only Kite readiness probe and guarded broker
methods. It does not implement this complete application workflow. Enabling an
environment flag does not supply the missing lifecycle or prove readiness.

Official broker references, checked on 9 November 2026:

- [Static IP for API orders](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip)
- [Orders and fill status](https://kite.trade/docs/connect/v3/orders/)
- [Historical candles](https://kite.trade/docs/connect/v3/historical/)
