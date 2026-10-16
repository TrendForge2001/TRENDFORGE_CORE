# R69.2 — Canonical Backtest Engine

R69.2 extracts historical execution mechanics from the R68.4 backtest service into a reusable, versioned engine.

## Canonical engine

The production engine is:

`backtest/backtest_engine.py::BacktestEngine`

Engine version:

`R69.2-v1`

The existing R68.4 strategy remains:

`EMA20_50_RSI / R68.4-v1`

The strategy version is intentionally unchanged because R69.2 changes execution architecture, not the EMA20/EMA50 + RSI decision rules.

## Execution semantics

The engine is deterministic and long-only.

- Signals are evaluated only from completed bars.
- A signal generated at bar close is filled at the next bar open.
- Same-close fills are forbidden.
- Only one long position may be open at a time.
- Position sizing uses all available cash with integer shares.
- Transaction costs are applied in basis points on entry and exit notionals.
- Slippage is applied adversely to entry and exit fills.
- Open positions are force-closed at the final close by default.
- The engine never places paper or broker orders.

Canonical execution model:

`signal_close_fill_next_open`

Canonical sizing model:

`all_available_cash_integer_shares`

## Strategy boundary

`BacktestEngine` is strategy-agnostic.

A strategy supplies two functions:

- entry rule: completed previous/current bars -> mapping or None
- exit rule: completed previous/current bars -> mapping or None

The engine owns:

- pending next-bar execution;
- cash and position accounting;
- quantity calculation;
- transaction costs;
- slippage;
- trade ledger construction;
- equity curve;
- buy-and-hold comparison;
- win/loss statistics;
- profit factor;
- expectancy;
- maximum drawdown;
- Sharpe ratio;
- exposure percentage;
- forced final exit.

## Production service integration

`services/backtest_service.py` still owns:

- market-data retrieval;
- indicator calculation;
- EMA20/EMA50 + RSI strategy rules;
- input validation;
- run locking;
- provider observability;
- persistence;
- API-facing result assembly.

It now delegates the historical simulation to `BacktestEngine`.

Backtest responses expose engine provenance:

```json
{
  "engine": {
    "name": "BacktestEngine",
    "version": "R69.2-v1",
    "execution_model": "signal_close_fill_next_open",
    "position_sizing": "all_available_cash_integer_shares"
  }
}
```

Backtest readiness also reports the canonical engine and version.

## Metrics

The canonical engine returns:

- initial capital
- final capital
- net profit
- return %
- buy-and-hold return %
- excess return vs buy-and-hold
- total trades
- wins / losses
- win rate
- average win / average loss
- expectancy
- profit factor
- max drawdown %
- Sharpe ratio
- exposure %
- transaction costs
- estimated slippage impact

When forced final exit is disabled, final-capital metrics use final marked-to-market equity rather than cash alone.

## Safety

R69.2 is historical simulation only.

It does not:

- create paper orders;
- place Kite/broker orders;
- modify R67.2 paper-entry gates;
- modify R67.3 analysis/execution eligibility;
- weaken kill-switch or risk controls;
- change live-trading permissions.

R67.3 remains independently production-verified.
