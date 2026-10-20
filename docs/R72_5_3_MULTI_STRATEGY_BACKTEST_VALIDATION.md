# R72.5.3 — Multi-Strategy Backtest & Strategy Validation Engine

R72.5.3 validates the standalone executable strategies introduced by R72.5.1
and wired into the R72.5.2 scanner.

## Execution model

Every strategy uses the same realistic historical execution model:

- signal generated only after a completed candle;
- entry and ordinary strategy exits fill at the next candle open;
- fixed ATR-derived stop and target based only on information available at the
  entry signal;
- conservative stop-first resolution when a candle hits stop and target;
- transaction costs and slippage;
- intraday forced square-off at 15:00 IST;
- unfilled intraday entry signals are cancelled at 15:00 and are never carried
  into the next trading day;
- independent capital per symbol/strategy.

Intraday uses 15-minute candles and session-reset VWAP / prior-session
Fibonacci pivots. Swing and positional validation use daily candles.

## Validation scope

The engine supports NIFTY 100, NIFTY 200 and NIFTY 500. A run may select one
or more universes and one or more modes:

- intraday: 60d history, 4 bps transaction cost + 5 bps slippage per side;
- swing: 2y history, 12 bps transaction cost + 5 bps slippage per side;
- positional: 5y history, 12 bps transaction cost + 5 bps slippage per side.

Candles are strict Kite-only. Fundamentals and enrichment are not used.

## Strategy isolation

Each standalone executable strategy is backtested independently. Review-required
notebook rules and confirmation-only RSI logic are excluded from standalone
backtests rather than guessed.

## Metrics

For every strategy × mode × universe, the result includes:

- tested/completed/error symbols and universe coverage;
- aggregate test capital, final capital, P&L and return;
- average and median symbol return;
- profitable/loss-making symbols and profitable-symbol percentage;
- total trades, wins, losses and win rate;
- gross profit/loss, profit factor and expectancy;
- average/worst drawdown and average Sharpe ratio;
- transaction costs and slippage impact.

Aggregate P&L is a research aggregation of independent symbol tests, not a
concurrent portfolio.

## Validation gate

A strategy-universe result is INSUFFICIENT_DATA until it has:

- at least 90% of the selected universe represented;
- at least 20 completed symbols;
- at least 30 trades.

After minimum data is satisfied, PASS requires:

- at least 90% candle/backtest coverage;
- positive aggregate net P&L;
- at least 50% profitable symbols;
- profit factor >= 1.10;
- positive median symbol return;
- average max drawdown <= 15%;
- worst max drawdown <= 35%.

A strategy becomes ELIGIBLE_FOR_REVIEW only when every selected universe for
that strategy/mode passes and the registry marks it paper-eligible.

ELIGIBLE_FOR_REVIEW does not enable paper trading. R72.5.3 performs no paper
orders, broker orders, automatic promotion or automatic validation runs.

## API

- GET /technical/multi-strategy/validation/readiness
- GET /technical/multi-strategy/validation/status
- POST /technical/multi-strategy/validation/run
- GET /technical/multi-strategy/validation/export

Run and export endpoints require the Admin API Key.

## Streamlit

The Technicals page provides staged/full-universe validation controls, live
progress, promotion-gate counts, one tab per strategy, per-universe metrics and
a JSON export.
