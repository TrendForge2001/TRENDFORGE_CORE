# Additional short scanners and paper execution diagnostics

The active catalog contains six original source definitions and five owner-requested
intraday short pairs: eleven definitions, nine executable, two review-only.
The three additional research pairs below use the same scanner evaluator in
historical backtests and simulated paper entry. They are original configuration
choices for this request, not copied Streak presets or profitability claims.

| Pair | Completed 15-minute entry conditions | Strategy cover condition |
|---|---|---|
| Session VWAP Breakdown | Previous close at/above its session VWAP, current close below its session VWAP; EMA9 < EMA20 | Close above session VWAP or RSI14 ≥ 60 |
| 20-Candle Low Breakdown | Previous close at/above its prior-20-candle low; current close below its prior-20-candle low and EMA20 | Close above EMA20 or RSI14 ≥ 60 |
| EMA / ADX Bearish Continuation | EMA20 < EMA50, ADX ≥ 20, −DI > +DI, close below the previous completed candle low | Close above EMA20, +DI > −DI, or RSI14 ≥ 60 |

All three additionally require RSI14 ≤ 45, volume above its 20-candle moving
average, a positive ATR bracket and two consecutive candles in the same NSE
session. The signal candle must start at/after 09:45 IST and before 14:45 IST.
Automation's existing entry cutoff is before 14:45 IST, so a later-closing
signal cannot create an entry after the cutoff.

The stop is entry + 1.5 × ATR and the target is entry − 2 × initial risk/share.
Targets must remain positive. Shorts use full-notional collateral, no leverage,
no overnight holding, and the existing 15:00 IST square-off. Existing cash-reserve,
position, daily-loss, validation, duplicate-entry, quote freshness, storage and
kill checks remain mandatory. Paper statements show gross simulated P&L;
backtests separately deduct configured transaction costs and slippage.

`VWAP_SESSION` resets at the Asia/Kolkata date boundary, independent of the
history lookback or input timezone. The legacy `VWAP` column is retained for
compatibility. `LOW_20_PREV` excludes the signal candle and may include prior
sessions. Neither new reference reads future candles. The continuation strategy
does not require a fresh EMA crossover, but it still requires the full bearish
setup. Falling broad-market prices alone cannot produce an approved trade.

The registry version changes to `source-six-with-five-intraday-shorts-v3`.
Previous validation cannot approve the new catalog. Run full NIFTY 500 validation
for all modes/source `all`, without a symbol limit; failed validation is not
bypassed. Single-strategy candle evaluation avoids constructing unrelated
catalog metadata, reducing repeated work during historical validation.

## Interpreting zero trades

`enabled=true` and `watching_market` describe the worker, not a fill. In the paper
workspace, **Paper execution diagnostics** now shows:

- Validation phase and whether it covers the current catalog and universe.
- Scan IDs, requested/completed/error counts and candidate counts by mode.
- Each strategy's scanner matches, candidate count, risk approvals, opened count
  and exact recorded validation/risk/fresh-data rejection codes.
- A cycle result of `opened`, `blocked` or `no_entry_signals`.

Idle polls retain the last actual scan/entry report. Previously, review-only
positional rows could overwrite that report every 15 seconds and hide its
rejection reasons. Risk-preview rejections are now included even when the
canonical entry processor was never called. A degraded/incomplete NIFTY scan
still blocks entry; this change does not silently promote partial data.

The cycle is held in process memory. Existing SQLite scanner, validation,
execution-claim and trade lineage remain the durable evidence. Restart leaves
automation OFF and requires the operator to review and Start again.

Blue/teal panels, coloured buttons, signal labels and signed P&L cells improve
readability. The text labels and financial values remain visible; CSV/Excel
exports use the original numbers, not display styles. Five top-level tabs and
the left-controls/right-results layout remain intact.

The active screens use Streamlit's `width` argument instead of the deprecated
`use_container_width` argument. Those warnings did not establish a trading
failure, but removing them keeps operational logs readable.

## PC checks

If PowerShell reports **Unable to connect** for `127.0.0.1:10000`, the backend is
not reachable from that PC. This cannot establish a scanner failure. Inspect
the original server window and restart the reviewed launcher if it was closed;
preserve `%LOCALAPPDATA%\TrendForgeCore`, its database, private keys and paired
storage proof. Do not delete the ledger or lock/proof to remove a blocker.

Updating GitHub/Render does not update a downloaded PC release. Install the new
release, keep its server PowerShell window open, then use `-CheckPaper` from a
second window as documented in [NIFTY500_PAPER_STATUS.md](NIFTY500_PAPER_STATUS.md).
The diagnostic does not start trades. Check Kite authentication and fresh quotes,
validate the updated catalog, and explicitly Start paper automation in NIFTY 500.
The diagnostic and Live Kite readiness button also request a completed historical
candle sample and calculate the active intraday indicators. `history_status` and
`indicator_status` distinguish this probe from a login/quote-only check. The
sample cannot establish data availability for every NIFTY 500 stock.
Any real broker order path remains guarded; controlled tests use broker reads
and simulated SQLite fills only.

## Release verification

The local full regression suite passes 2,226 tests with four platform/optional
skips. The focused short/execution checks pass 37 tests with deprecation warnings
treated as errors. They exercise all five short rules through the real scanner,
automation, risk admission, canonical paper service and SQLite trade ledger,
including target exits, stop-loss exits, duplicate protection and lineage. They
use controlled quote/history/validation/storage fixtures, not the owner's account
or live market prices. Separate recovery tests cover actual Windows storage.

Desktop 1366×768 and mobile 390×844 browser fixtures cover all five active
screens without page exceptions or horizontal page overflow. Syntax checks and
runtime undefined-name/import lint also pass. No new production dependency is
required. The catalog-filter optimization preserves evaluation results; one
local 500-evaluation comparison took 0.039s versus 0.089s before the change.
This is a component benchmark, not a live NIFTY 500 latency guarantee.
