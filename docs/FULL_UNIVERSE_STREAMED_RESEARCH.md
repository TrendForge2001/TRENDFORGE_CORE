# Full-universe weekly research — 15 November 2026

The earlier five-year admission budget of 150,000 daily candles effectively
limited a shared-account run to about 100 stocks. NIFTY 200 and NIFTY 500 could
not be admitted under that in-memory policy. Larger scans produced independently
stored child reports and a parent index rather than one consolidated scan.

The current weekly strategy now uses one background job per selected universe:

- Scans fetch at most 25 stocks at once, retaining only result/evidence rows and
  coverage metadata. The final report contains all selected members, including
  individual data/warm-up errors. No child-portfolio manifest or top-100 truncation
  is used for these scans.
- Backtests stage one stock's normalized daily prices and confirmed entry events
  into temporary SQLite storage while fetching chunks of 25. The cache is capped
  at 4 MiB and memory mapping is disabled. Four comparisons read one session at a
  time, carrying the same cash, positions and risk limits across all stocks.
  Signals are computed once per stock; no chunk receives fresh capital.
- The bounded staged-history budget is 1,500,000 observations, sufficient for up
  to 1,000 selected stocks with five years of warm-up. Each fetch chunk retains its
  50,000-observation guard. These are observation/admission limits, not capital
  limits. Legacy non-streamed strategies retain their prior 150,000-row policy.
- Temporary files are removed after success or exceptions. An isolated worker's
  outer scratch directory is owned by its parent so cancellation/child death also
  removes staged prices. Final reports still use the persistent report archive.

The original weekly conditions, next-session timing, per-stock warm-up, four
comparison policies, structural stops, frozen R2 and costs are unchanged. Exact
reference-vs-disk tests cover all four policies with unequal stock calendars.
The period and stock-list selectors remain. NIFTY 200, NIFTY 500 and the listed
250-stock universes use the complete validated membership, not an arbitrary
100-stock subset. Eligibility errors remain visible rather than manufacturing
missing market history.

Acceptance runs a consolidated 500-stock scan and four-stage backtest under
0.5 CPU and 512 MiB, verifies CSV/Excel/JSON checksums, and recovers reports after
restart. Artificial data verifies the engine and resource behavior; actual market
verification is recorded separately.

The optional `TRENDFORGE_RESEARCH_CAMPAIGN` operator intent can schedule one scan
and one backtest for NIFTY 200/500 from the official constituent loader, using a
chosen 2y/5y period and explicit unique request ID. A durable claim prevents
repeating the campaign across restarts. It is disabled by default, restricted to
the original Render service and does not enable paper or real broker orders.
