# NIFTY scanner and paper candidate capacity

The technical scan API, technical scanner selection, named multi-strategy scan
ranking and paper target controls now share a 1,000-symbol ceiling. This permits
the full NIFTY 500 list, including constituent lists with more than 500 securities,
without the former 100-target rejection or 100-candidate truncation. Explicit
paper targets must still be verified members of the chosen validation universe.

Technical scans and automated multi-strategy scans fetch and evaluate 25 stocks
at a time. Raw frames from a finished batch are released before the next fetch.
Provider-owned frame mappings are preserved. Existing Kite historical request
pacing and the provider's bounded worker pool remain in force; capacity does not
mean sending 1,000 simultaneous requests. Browser scans use separate short batch
requests and display processed/total counts. Paper automation exposes the same
progress through `scanner_progress` in `GET /paper/automation`.

Automated scans request all ranked candidates up to the shared ceiling so a
valid signal after rank 100 can reach the canonical paper admission boundary.
Next-candle trigger checks remain on their separate worker. Quote requests are
split at Kite's 500-instrument limit, with at least 1.05 seconds between starts of
successive quote batches. Every requested quote must still have a valid price and
fresh exchange timestamp; missing or stale quotes do not become simulated fills.

The wider candidate universe does not change the three concurrent stock limit,
₹80,000 deployment ceiling, ₹20,000 entry reserve, per-trade risk, validation,
verified storage, kill switch, short-availability assumption or broker lock.
Stop cancels pending entries and restart keeps automation OFF. Incomplete or
degraded scans retain their existing admission restrictions.

The portfolio-backtest form retains its separate 100-stock research selection
limit. This release increases scanner and paper candidate capacity, not the
historical shared-portfolio simulation limit.

Functional tests cover 500/501-stock scans, bounded batches, full target
Start/Stop and restart read-back, UI handoff of 500 stocks, 1,000-quote batching,
stale-tail rejection, and paper fills from stocks after the first 100 while
retaining three positions and the capital limit. These use controlled market
data and real paper ledger admission; they are not a live Kite throughput or
strategy-profitability benchmark. Real scan duration still depends on Kite
latency, rate limits and the machine hosting TrendForge.
