# R71.5 — Technical Strategy Validation & Backtest Realism

## Scope

R71.5 keeps the fundamentals/enrichment scanner outside the technical path and
extends R71.2 with realistic historical execution and broad-market validation.

### Data policy

- Historical OHLCV: **Kite Connect only**.
- Universe membership: official NSE constituent CSVs.
- Universes: NIFTY 100, NIFTY 200 and NIFTY 500.
- NIFTY 100/200 are derived from their own official membership while historical
  data is fetched only once for the union (normally the NIFTY 500 set).
- No Yahoo fallback in the technical validation service.
- No fundamentals or enrichment data participates in signals.
- No paper or broker order is created by validation/backtests.

## Realistic execution model

- Signal evaluated only after a completed candle.
- Entry and ordinary technical exit fill at the next candle open.
- Long-only, one independent position per symbol simulation.
- Integer-share sizing from independent test capital.
- ATR stop and target are fixed using data known at the entry signal.
- Stop/target are evaluated against each following candle's high/low.
- If both are touched in the same candle, **stop-first** is assumed.
- Gap through a stop executes at the adverse open.
- Intraday positions are force-exited at **15:00 IST** and cannot carry overnight.
- Transaction costs and slippage are applied per side.

Default broad validation assumptions:

| Mode | History | Cost / side | Slippage / side |
|---|---:|---:|---:|
| Swing | 2y | 12 bps | 5 bps |
| Intraday | 60d | 4 bps | 5 bps |

These are research assumptions, not a tax/brokerage statement.

## Aggregation semantics

Every symbol is backtested independently with ₹100,000 by default. Therefore
the NIFTY-level aggregate P/L is the sum of independent tests and the aggregate
capital is completed-symbol-count × ₹100,000. It is **not** a concurrent
portfolio simulation and does not model cross-symbol capital competition.

## API

- GET /technical/validation/readiness
- GET /technical/validation/status
- POST /technical/validation/run
- GET /technical/validation/export (admin-key header; JSON download)

POST remains behind the existing production admin-key middleware. Export uses a
separate runtime token and contains research results only.

## Streamlit

Technical Lab now exposes:
- R71.5 execution-realism disclosure.
- Mode-specific realistic default friction assumptions.
- NIFTY 100/200/500 validation start/status/summary.

## Safety

- Fundamentals used: false.
- Enrichment used: false.
- Paper orders from validation: false.
- Broker orders allowed: false.
- Existing paper kill switch/risk gate are unchanged.
