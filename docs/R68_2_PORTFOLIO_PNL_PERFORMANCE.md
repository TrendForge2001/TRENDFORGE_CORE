# R68.2 Portfolio, P&L and Performance

R68.2 adds canonical reporting contracts and Streamlit pages for persisted broker portfolio state and realized paper-trading analytics.

## API contracts

### GET /portfolio

Read-only persisted live-portfolio snapshot.

Response fields include:

- status
- scope = persisted_live_portfolio
- count
- holding_count
- position_count
- investment
- portfolio_value
- total_pnl
- total_pnl_pct
- latest_updated_at
- holdings[]
- positions[]
- book_summary[]
- sector_summary[]

The endpoint never places broker orders.

### POST /portfolio/sync

Explicit broker refresh.

The endpoint:

1. requires a configured/authenticated Kite provider;
2. reads Kite holdings;
3. reads the Kite net positions book;
4. replaces the persisted live_portfolio snapshot;
5. returns the synchronized snapshot summary.

Production middleware treats this as an admin-protected operation.

### GET /pnl

Query:

    period=daily|weekly|monthly|yearly|all

Scope:

    paper_trading_closed_trades

The endpoint reports calendar-period realized paper-trading P&L:

- gross profit
- gross loss
- net P&L
- winning / losing / breakeven trade counts
- sum of entry capital employed
- average capital per trade
- average daily capital employed
- P&L margin
- daily aggregation
- trade-level evidence

Period boundaries use Asia/Kolkata:

- daily = current calendar day
- weekly = current Monday-to-now week
- monthly = current calendar month
- yearly = current calendar year
- all = all closed history

### GET /performance

Uses the same period and scope as /pnl and adds:

- win rate
- profit factor
- average winner
- average loser
- expectancy
- maximum absolute drawdown
- best trade
- worst trade
- cumulative realized P&L curve

Profit factor is null when there is no gross loss because the ratio is undefined.

## Trade close timestamp

R68.2 evolves trade_history with:

    closed_at DATETIME

New closures persist an Asia/Kolkata timestamp.

The migration is backward compatible. Existing closed rows retain closed_at=NULL.

Reporting uses:

    closed_at

when available and otherwise falls back to:

    created_at

Legacy fallback rows are explicitly tagged:

    date_basis = legacy_entry_fallback

The API also declares:

    date_basis = closed_at_with_legacy_entry_fallback

so historical attribution is not silently presented as true close-time accounting.

## Canonical database lifecycle

The live_portfolio migration was previously present only in the legacy migration runner.

R68.2 adds live_portfolio to:

- core.database.MIGRATIONS
- core.database.REQUIRED_TABLES

A clean canonical FastAPI boot therefore guarantees the portfolio table exists.

## Kite positions compatibility

Kite positions commonly return:

    {
      "day": [...],
      "net": [...]
    }

R68.2 explicitly uses the net list for persisted POSITION rows. This avoids duplicating day and net books and makes the live refresh contract compatible with the broker response shape.

## Webapp pages

### Portfolio

- investment/current value/P&L metrics
- holdings and positions kept separate
- book summary
- delivery sector allocation
- CSV exports
- admin-gated Refresh from Kite

### P&L Statement

- daily/weekly/monthly/yearly/all period selector
- realized P&L scorecard
- average capital/day and per trade
- daily realized P&L chart
- trade evidence table
- CSV export
- warning when legacy timestamp fallback is used

### Performance Dashboard

- net P&L
- win rate
- profit factor
- expectancy
- maximum drawdown
- average winner/loser
- winning/losing trade counts
- cumulative realized P&L curve
- best/worst trade evidence

## Scope separation

R68.2 deliberately does not combine:

- broker portfolio mark-to-market P&L; and
- paper-trading realized P&L.

The Portfolio page represents broker books. P&L and Performance represent TrendForge paper execution history.

## Compatibility

R68.2 does not change:

- scanner strategy, scoring or indicators;
- scan continuation semantics;
- provider priority for market data;
- R67.2 paper auto-entry safety gates;
- live broker order authorization;
- backend Render deployment manifest.

The existing Render Free ephemeral-storage boundary still applies to SQLite portfolio/trade history.
