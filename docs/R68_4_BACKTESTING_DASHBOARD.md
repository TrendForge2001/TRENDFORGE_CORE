# R68.4 Backtesting Dashboard and API Contracts

R68.4 closes the remaining major R68.0 webapp roadmap gap by adding a canonical historical backtesting boundary and a dedicated Streamlit dashboard.

## Scope

R68.4 deliberately introduces one transparent baseline strategy rather than an optimizer or strategy generator.

Strategy:

    EMA20_50_RSI

Version:

    R68.4-v1

The version is persisted with every run so future strategy revisions do not silently reinterpret old results.

## API contracts

Read-only:

    GET /backtests/readiness
    GET /backtests?limit=<1..500>&symbol=<optional>
    GET /backtests/{run_id}

Admin-protected historical execution:

    POST /backtests

Example request:

    {
      "symbol": "TCS",
      "period": "2y",
      "interval": "1d",
      "capital": 100000,
      "rsi_threshold": 60,
      "ema_proximity_pct": 1.0,
      "cost_bps": 0,
      "slippage_bps": 0
    }

Supported history windows are 1y, 2y and 5y using daily candles.

## Strategy contract

Entry signal:

1. EMA20 crosses above EMA50 on a completed daily bar.
2. RSI is greater than or equal to the configured threshold.
3. Closing price is within the configured percentage distance of EMA20.

Exit signal:

1. EMA20 crosses below EMA50; or
2. RSI falls below the configured threshold.

The baseline is long-only and permits one open position at a time.

## No-look-ahead execution

The signal bar is never used as the fill bar.

A signal calculated after today's close can execute only at the next available bar's open.

Therefore:

    signal at bar N close
    fill at bar N+1 open

The same rule applies to exits.

If the test ends with an open position, R68.4 forces a final liquidation at the last available close and labels the exit reason:

    END_OF_TEST

## Position sizing

R68.4 uses:

    all_available_cash_integer_shares

For each entry it calculates the largest integer quantity affordable from current cash after configured entry transaction cost.

Profits/losses compound into subsequent trades.

No leverage, pyramiding, shorting, options or derivatives are introduced in this baseline.

## Friction model

Two independent parameters are supported per side:

- transaction cost in basis points
- slippage in basis points

Buy slippage increases the simulated fill price.

Sell slippage decreases the simulated fill price.

Transaction cost is charged against executed notional on entry and exit.

The response reports:

- transaction_costs
- slippage_impact_estimate

A value of zero for both parameters produces a frictionless historical simulation and should not be interpreted as a net-of-charges trading result.

## Metrics

Each completed run returns:

- initial capital
- final capital
- net profit
- strategy return
- buy-and-hold return
- excess return vs buy-and-hold
- total trades
- wins / losses
- win rate
- average win
- average loss
- expectancy
- profit factor
- maximum drawdown
- annualized daily Sharpe ratio using zero risk-free rate
- exposure percentage
- transaction costs
- estimated slippage impact

It also returns the full trade ledger and daily equity curve.

## Persistence

R68.4 evolves the existing:

    backtest_results

table in place.

New fields include:

- run_id
- strategy_version
- status
- initial_capital
- final_capital
- return_pct
- buy_hold_return_pct
- profit_factor
- expectancy
- exposure_pct
- cost_bps
- slippage_bps
- parameters_json
- result_json

Existing legacy summary-only rows remain readable.

New detailed runs are uniquely addressed by run_id.

## Webapp

The Backtesting page provides:

- service readiness
- symbol and period selection
- initial capital
- RSI threshold
- EMA20 proximity
- transaction-cost input
- slippage input
- persisted run history
- run-detail loading
- strategy vs buy-and-hold chart
- equity curve
- trade ledger
- CSV trade export
- strategy/parameter evidence
- provider evidence
- safety state

## Safety boundary

Backtesting is historical simulation only.

R68.4:

- does not place broker orders
- does not open paper positions
- does not alter scanner signals
- does not enable live trading
- does not bypass the existing R67 risk controls
- does not introduce an optimizer

Only POST /backtests is admin protected because it performs market-data work and persists a new run.

Backtest readiness, history and detail remain read-only.

## Storage limitation

Detailed run history is stored in the backend SQLite database.

The existing Render ephemeral-storage limitation still applies. Historical backtest rows can disappear after instance replacement or redeployment until durable backend storage is enabled.
