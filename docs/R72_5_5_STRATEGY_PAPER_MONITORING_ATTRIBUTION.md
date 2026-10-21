# R72.5.5 — Strategy Paper Position Monitoring, Exit Signals & Performance Attribution

R72.5.5 extends the R72.5.4 strategy-driven paper entry path with durable
strategy lineage, completed-candle exit evaluation, and per-strategy paper P&L.

## Execution boundary

R72.5.5 remains paper-only.

It does not:

- send broker orders;
- bypass the paper kill switch for new entries;
- alter the R67.2 entry-risk gate;
- reinterpret ambiguous strategies;
- create a new live-trading path.

Existing protective exits remain authoritative and execute before strategy exits:

1. stop loss;
2. target;
3. 15:00 IST intraday force exit;
4. strategy exit signal for positions still open.

Swing positions remain exempt from the 15:00 force exit but remain subject to
stop, target and strategy exits.

## Durable lineage

Every R72.5.4/R67.2 strategy-driven paper trade can now persist:

- strategy ID;
- strategy name;
- strategy source;
- source scanner run ID;
- R72.5.3 validation run ID;
- entry strategy score;
- entry consensus score;
- entry signal;
- entry completed-candle timestamp;
- trade mode.

On close, the trade can additionally persist:

- exit reason;
- exit signal;
- completed candle that produced the exit signal;
- exit-strategy score.

The migration is additive to the existing `trade_history` table and is safe for
legacy databases.

## Strategy exit monitoring

`StrategyPaperMonitorService` evaluates only open paper positions that contain
strategy lineage.

For every supported position:

- the position's own strategy ID is evaluated;
- the position's original paper mode is retained;
- intraday uses 15-minute Kite candles;
- swing uses daily Kite candles;
- only completed candles are considered;
- the existing R72.5 multi-strategy engine is reused;
- only an explicit `EXIT` from that same strategy can trigger a strategy close;
- the simulated exit price is the current Kite LTP;
- the close is delegated to the canonical `PaperTradingService`.

Manual/non-strategy paper positions are ignored by the strategy evaluator.

## Automatic rollout safety

Automatic strategy-exit checks default OFF:

```text
TRENDFORGE_STRATEGY_PAPER_MONITOR_ENABLED=false
```

The default check interval is five minutes:

```text
TRENDFORGE_STRATEGY_PAPER_MONITOR_INTERVAL_SECONDS=300
```

When enabled, the existing paper quote-monitor loop invokes the strategy exit
monitor after applying ordinary SL/target/force-exit rules.

The admin-gated manual strategy-exit check remains available even when automatic
monitoring is disabled. This permits supervised validation before automatic
rollout.

## Performance attribution

Closed paper trades are grouped by strategy and trade mode. The attribution API
reports:

- closed trades;
- wins;
- losses;
- win rate;
- net P&L;
- average P&L;
- return on aggregate entry notional;
- first entry timestamp;
- latest exit timestamp.

The dashboard also reports current strategy-attributed open positions with:

- symbol;
- strategy;
- mode;
- entry;
- LTP;
- quantity;
- unrealized P&L;
- scanner run lineage;
- validation run lineage.

## API

Read strategy-monitor readiness:

```text
GET /paper/strategy-monitor/readiness
```

Run a supervised strategy exit check:

```text
POST /paper/strategy-monitor/tick
```

The manual tick requires the Admin API Key.

Read aggregated strategy paper performance:

```text
GET /paper/strategy-performance
```

Read recent strategy-attributed paper trades:

```text
GET /paper/strategy-trades
GET /paper/strategy-trades?strategy_id=tpl_supertrend_rsi&limit=200
```

## Streamlit

The Paper Trading Portfolio page now shows:

- strategy-exit monitor state;
- strategy-attributed open positions;
- per-strategy realized performance;
- recent strategy-attributed trade history;
- an admin-gated manual **Run Strategy Exit Check** action;
- the full latest exit-evaluation evidence.

## Safety guarantees

R72.5.5 continues to report:

```text
paper_only=true
broker_orders_allowed=false
```

A strategy exit closes only an already-open simulated position. It does not open,
reverse, short, or submit an order to Kite.
