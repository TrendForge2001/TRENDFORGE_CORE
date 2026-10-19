# R71.2 — Technical Scanner Paper Trading & Backtesting

R71.2 creates a separate technical-only research/execution path. The existing
fundamentals scanner remains unchanged.

## Scope

The new path supports:

- intraday technical scan: 15-minute Kite candles;
- swing technical scan: daily Kite candles;
- explicit technical evidence and 0-100 score;
- ATR-derived paper stop/target references;
- risk-governed paper entry through the existing R67.2 paper auto-entry gate;
- deterministic historical backtesting through the canonical BacktestEngine;
- persisted technical backtest results in the existing backtest-results store;
- Streamlit Technical Lab controls.

Fundamentals, corporate actions, institutional enrichment and sector enrichment
are not read by this service.

## Data policy

Technical Lab uses a strict Kite-only market-data adapter:

`ProviderFactory.kite_market_data()`

It contains only `KiteProvider`, disables provider fallback and does not invoke
the NSE symbol resolver. A missing/expired Kite access token therefore fails
closed instead of silently using Yahoo.

## Profiles

### Intraday

- interval: 15 minutes
- history: 30d / 45d / 60d
- EMA9 > EMA20
- EMA20 > EMA50
- VWMA9 > VWMA26
- close > VWAP
- RSI momentum band
- MACD bullish
- ADX/+DI directional strength
- relative-volume confirmation
- fresh trigger: EMA9/EMA20 bullish cross or fresh breakout
- reference stop: 1.5 ATR
- reference reward:risk: 2.0
- backtest blocks late entries and requests an end-of-session exit

### Swing

- interval: 1 day
- history: 1y / 2y / 5y
- EMA20 > EMA50
- EMA50 > EMA100
- close > EMA20
- VWMA9 > VWMA26
- RSI momentum band
- MACD bullish
- ADX/+DI directional strength
- relative-volume confirmation
- fresh trigger: EMA20/EMA50 bullish cross, fresh breakout or EMA20 reclaim
- reference stop: 2 ATR
- reference reward:risk: 2.0

Both profiles are long-only in R71.2.

## Execution safety

`POST /technical/scan` defaults to preview only.

If `execute_paper=true`, BUY candidates are passed into the existing
`PaperAutoEntryService`. That keeps the existing:

- paper-trading feature flag;
- paper kill switch;
- minimum score/confidence;
- risk-per-trade sizing;
- maximum capital per position;
- maximum open positions;
- maximum daily loss;
- duplicate-symbol/day guard;
- market-hours guard;
- maximum paper entries per scan.

No broker order endpoint is called.

## Backtesting

`POST /technical/backtest` uses the canonical
`backtest/backtest_engine.py::BacktestEngine`.

Execution remains:

- completed-bar decisions;
- next-bar-open fills;
- adverse configurable slippage;
- configurable transaction cost;
- integer-share sizing;
- long-only single position;
- final forced exit.

The ATR stop and target shown by the technical scanner are paper-risk references
in R71.2. The historical engine continues to exit on technical strategy signals
(and the intraday session-exit rule), not simulated intrabar stop/target fills.
That distinction is intentional and explicit to avoid claiming price-path
precision the current event engine does not provide.

## API

- `GET /technical/readiness`
- `POST /technical/scan`
- `POST /technical/backtest`

Technical backtests are also visible through the existing persisted backtest
history endpoints because they use the same backtest-results repository.

## UI

Streamlit navigation now includes:

`Operate -> Technical Lab`

The page provides:

- intraday/swing mode selector;
- symbol-list technical scan;
- optional paper execution;
- result ranking and evidence;
- single-symbol technical backtest;
- performance metrics and trade ledger;
- provider attribution and safety provenance.

## Non-goals

R71.2 does not:

- change the fundamentals scanner;
- change the NIFTY 500 scoring engine;
- place live broker orders;
- add short selling;
- simulate intrabar SL/target fills;
- weaken existing paper safety gates.
