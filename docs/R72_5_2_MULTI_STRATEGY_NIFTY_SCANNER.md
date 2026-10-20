# R72.5.2 — Multi-Strategy NIFTY Scanner Engine

R72.5.2 wires the R72.5.1 strategy registry into a scanner-only execution
path for NIFTY 100, NIFTY 200 and NIFTY 500.

## Data and execution boundary

- Historical/candlestick source: strict Kite-only market-data adapter.
- Fundamentals and enrichment: excluded.
- Paper trading: not connected to this scanner.
- Broker orders: disabled.
- Automatic scheduling: disabled.
- Full-universe runs execute in a background thread so API liveness is not
  blocked by long Kite historical-data retrieval.

The existing R72.3/R71.5 paper automation remains on the legacy technical
profiles until a later validation batch explicitly promotes multi-strategy
signals into paper execution.

## Supported scanner modes

| Mode | Interval | Default history |
| --- | --- | --- |
| intraday | 15m | 60d |
| swing | 1d | 2y |
| positional | 1d | 5y |

Intraday evaluation overwrites the shared historical VWAP with a session-reset
VWAP and derives Fibonacci pivots from the prior trading session for this
scanner only.  This avoids changing the legacy paper scanner semantics.

## Strategy fidelity

R72.5.2 evaluates deterministic rules with per-rule pass/fail evidence.
Notebook wording that does not define an exact executable condition is not
guessed.

Review-required strategies:

- `tf_intraday_supertrend_vwap_pivots`
- `tf_swing_macd_trend`
- `tf_medium_ema50_100`
- `tf_long_ema100_200`
- `tf_rsi_mean_reversion`

`tf_rsi_momentum_confirmation` is confirmation-only.  It can produce
`CONFIRM_BUY` or `CONFIRM_SELL`, but never creates a standalone BUY
candidate.

## Consensus

A symbol result exposes:

- standalone BUY strategy count;
- notebook/template BUY counts;
- bullish confirmation count;
- exit count;
- matched strategy IDs;
- consensus score;
- primary strategy and ATR risk reference;
- `STRONG_BUY`, `BUY`, `WATCH`, `EXIT` or `NEUTRAL`.

A STRONG_BUY requires at least one notebook-derived BUY plus agreement from at
least one additional standalone strategy and sufficient consensus score.

## API

- `GET /technical/multi-strategy/readiness`
- `GET /technical/multi-strategy/status`
- `POST /technical/multi-strategy/run` — Admin API key required

The run endpoint accepts universe, mode, source, optional strategy IDs,
history period, top-N, optional staged symbol limit and universe refresh.

## UI

The Technicals page includes the R72.5.2 scanner with universe/mode/source
controls, staged/full-universe selection, progress state, ranked candidates,
strategy evidence and per-strategy scan summary.
