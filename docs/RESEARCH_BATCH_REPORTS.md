# Strategy horizons and research batch reports

The Scanner and Backtesting pages use separate strategy dropdowns under five
horizon tabs. Short Swing means quick multi-day trades; it does not mean short
selling. A bearish strategy is explicitly labelled separately.

| Horizon | Existing executable rules | Candles / history |
| --- | --- | --- |
| Intraday | Registered intraday source and EMA/pivot strategies | 15 minute / 60 days |
| Short Swing | EMA/pivot 9/26, bullish and bearish | Daily / 2 years |
| Short Term | Daily source strategies and EMA/pivot 20/50 | Daily / 2 years |
| Medium Term | EMA/pivot 50/100, bullish and bearish | Daily / 2 years |
| Long Term | EMA/pivot 100/200, bullish and bearish | Daily / 5 years |

These groups select existing rules and candle conventions. They do not guarantee
holding periods or change exit rules. The two incomplete legacy review-only
50/100 and 100/200 definitions remain excluded; their executable EMA/pivot
counterparts are available. Historical bearish simulation carries the visible
borrow assumption. Paper borrow must still be separately acknowledged.

After stock-list selection, Backtesting has exactly two actions: **Scan stocks**
and **Backtest**. Scanner has **Scan stocks**. Neither page mixes result tables
with its input controls. Paper execution keeps Start/Stop, monitor, exits and
kill controls; statements move to **Reports → Paper statements**. Watchlist
uses its search field and price table without a duplicate stock dropdown.

## Research lifecycle

A protected POST to `/reports/scan` or `/reports/backtest` accepts the horizon,
strategy ID, official stock-list label, symbols and explicit borrow assumption.
The server validates the strategy/horizon pair and chooses its candle history.
Capital, reserve, execution and arbitrary strategy-rule overrides are rejected.

Each accepted run receives a unique batch ID. One in-process background thread
executes research, with at most three running/queued batches together. A full
queue returns 429; clients do not retry POSTs automatically. No extra Render
worker service is provisioned. Run a single API process (`WEB_CONCURRENCY=1`),
one instance and one application worker for this SQLite deployment.

`research_batches` is an additive migration in the existing canonical database.
Queued, running, completed, failed and interrupted states remain distinct.
Phase counters and last-update times distinguish simulation work from history fetching.
Progress includes history retrieval, scanning/simulation and report generation.
The completed state and generated report are committed in one SQL update.
Exceptions expose a fixed error code, never raw provider exception text. A
restart marks unfinished work interrupted; it does not replay requests or place
orders. A new run preserves every previous batch record.

Reports refresh every ten seconds, offer older/newer batch pages and open the
selected batch by ID. GET `/reports/batches` supports `limit` and `offset`.
GET `/reports/batches/{id}` returns progress and the completed report;
GET `/reports/batches/{id}/report.csv` returns UTF-8 CSV only after completion; `/report.xlsx` returns the generated Excel workbook.
All report reads and writes require the Admin API Key.

## Automatic detailed reports

Completed portfolio backtests generate their report on the backend before
returning or saving a completed result. New batch backtests publish that same
report. Each actual exit fill has its original entry, entry quantity, exit
price/time/quantity/reason, allocated transaction costs and net P&L. Partial and
final exits share a trade number. Exported rows also carry run, strategy,
horizon, stock-list, mode, registry and report-type provenance. The report keeps
engine version, account policy, metrics and history alignment as run details.
Daily candle timestamps identify bar dates, not exact intrabar fill times.

Generation rejects inconsistent fill quantities, costs, P&L or equity evidence.
A zero-trade backtest is a completed report with headers and zero fill rows.
Scanner exports explicitly identify themselves as indicator snapshots; they
are never presented as historical trades. CSV formula text is escaped and the
report stores a SHA-256 checksum. CSV and Excel are generated together on the backend; both download buttons sit above the result table.

On first use, the latest 50 completed historical portfolio records are indexed
when available. Original capital policy is preserved. Legacy records without
sufficient evidence are marked `legacy_evidence_incomplete`; no fills are
invented. This compatibility import does not re-run a backtest.

## Storage and execution runtime

PC paper execution continues to use its configured durable SQLite path. Back
up that database before upgrading/migrating the PC installation. Keep the
existing books separate; cloud reports do not represent the PC paper ledger.

The chosen free Render service remains read-only for trading. Research is
permitted, but its filesystem is ephemeral: batches and exports on Render can
be lost on restart or deployment. Download reports to retain them, or run
research against the PC's durable database. This feature does not enable broker
orders or change paper/live admission rules.

The sidebar Core API badge now checks `/livez` with a two-second timeout and a
30-second cache. Connected means API process liveness; Kite authentication,
quote freshness and trading readiness remain separate checks.

See [runtime and report recovery](RESEARCH_RECOVERY.md) for automatic PC files,
cold-start routing and cloud preview capacity.
