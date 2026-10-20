# R72.5.1 — Strategy Registry & Indicator Completion

R72.5.1 introduces the canonical technical-strategy catalogue used by the
next scanner, backtest and paper-trading batches.

## Scope

- 12 notebook-derived TrendForge strategy definitions.
- 7 clearly labelled template-style technical strategies.
- Read-only strategy registry API and Streamlit registry viewer.
- Indicator completion:
  - EMA 9/20/50/100/200 (existing, retained)
  - VWMA 9/26/50/100
  - RSI 14 and RSI 20
  - smoothed RSI 14
  - MACD
  - ADX/+DI/-DI
  - Volume MA20 and MA50
  - VWAP
  - Supertrend (10,3)
  - ATR/Bollinger (existing, retained)
  - previous-period Fibonacci pivot levels
  - rolling 52-week high/low context

## Important execution boundary

This batch is declarative and read-only.  Existing intraday/swing execution
continues to use the R71.5 legacy technical profiles.  The registry reports
`execution_wiring=R72.5.2_pending`.

No scanner, backtest, paper order or broker order is started by installing
R72.5.1.

## Notebook fidelity

Where the handwritten notes contain ambiguous/conflicting statements, the
registry preserves those statements in the strategy's `ambiguities` field
instead of silently changing the rule.  The momentum RSI and mean-reversion
RSI interpretations are stored as separate strategies.

## API

- `GET /technical/strategies`
- `GET /technical/strategies/{strategy_id}`

The collection endpoint supports optional `mode` and `source` filters.
