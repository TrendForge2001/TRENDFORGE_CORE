# R68.3 Watchlists, Market Breadth and Market Regime

R68.3 adds canonical persisted watchlists plus snapshot-based NIFTY 500 market-context dashboards.

## Watchlist contracts

Read-only:

    GET /watchlists
    GET /watchlists/{name}

Admin-protected mutations:

    POST   /watchlists/{name}/symbols
    PUT    /watchlists/{name}/symbols/{symbol}
    DELETE /watchlists/{name}/symbols/{symbol}
    DELETE /watchlists/{name}

Each persisted entry can carry:

- symbol / exchange
- priority 1-5
- notes
- target
- stop-loss
- scanner name
- score
- last signal
- last scan timestamp

R68.3 also repairs the legacy repository/manager mismatch by exposing the compatibility methods expected by WatchlistManager while preserving the canonical repository API.

## Market context contracts

Read-only persisted snapshots:

    GET /market/breadth
    GET /market/regime

Explicit refresh:

    POST /market/context/refresh

Refresh request:

    {
      "limit": 100,
      "period": "1y",
      "interval": "1d",
      "refresh_universe": false
    }

Allowed sample sizes are 25-500 securities. One year or two years of daily history is supported so EMA200 and close-based high/low breadth have enough data.

The refresh endpoint is admin protected and guarded against overlapping execution.

Dashboard GET requests do not fan out to market-data providers. They read the most recently persisted snapshot.

## Breadth methodology

The source universe is the canonical NSE NIFTY 500 constituent list.

When the requested sample is smaller than the current security count, TrendForge chooses evenly spaced members across the canonical symbol-ordered list. A full 500 request uses the complete requested universe subject to current NSE security membership and provider success.

For every usable security TrendForge derives:

- latest daily percentage change
- EMA20
- EMA50
- EMA200
- close-based trailing high / low flag
- NSE constituent sector

The snapshot reports:

- advances / declines / unchanged
- advance-decline ratio and line
- new highs / lows
- percentages above EMA20 / EMA50 / EMA200
- sector average daily change
- coverage and failure evidence
- provider observation metadata

The public breadth_score is the bounded 0-100 canonical Breadth Engine score.

The older MarketBreadth EMA-weighted formula is retained as:

    ema_weighted_score_raw

for diagnostics only because the legacy formula is not bounded to 100.

R68.3 also fixes BreadthEngine input handling so legitimate zero counts, such as advances=0 in a fully declining market, are not treated as missing values.

## Regime methodology

The market regime is not inferred from a single stock and is not a trade signal.

TrendForge builds an equal-weight normalized composite from the same accepted NIFTY 500 sample:

1. each security's OHLC series is normalized to a common base;
2. normalized OHLC values are equally averaged by date;
3. volume is aggregated;
4. the canonical Indicator Engine enriches the composite;
5. the canonical Market Regime Engine evaluates the enriched composite;
6. current breadth advances/declines are supplied to the regime breadth component.

The regime contract exposes:

- BULLISH / BEARISH / SIDEWAYS / HIGH_VOLATILITY / RISK_OFF
- direction
- score
- confidence
- grade
- trend component
- momentum component
- volatility component
- participation component
- breadth component
- composite EMA / RSI / ADX / ATR% / RVOL evidence
- reasons and risk warnings

The methodology is explicitly returned as:

    equal_weight_normalized_sample_composite

## Snapshot persistence

R68.3 adds:

    market_context_snapshots

The table keeps the latest breadth and regime JSON payloads plus universe, sample size and timestamp.

The table is part of both canonical and legacy migration paths.

## Webapp pages

### Watchlists

- summary metrics
- named-list selection
- entry table and CSV export
- add/upsert symbol
- edit priority, target, stop-loss and notes
- remove symbol
- guarded entire-watchlist delete

### Market Breadth

- explicit refresh controls
- direction / score / coverage
- A/D metrics
- EMA breadth
- highs/lows
- sector participation
- provider and failure diagnostics

### Market Regime

- explicit refresh controls
- regime / direction / score / confidence / grade
- component score table/chart
- composite technical evidence
- regime reasons
- risk warnings

The Command Center also surfaces the latest persisted regime and breadth state.

## Safety and durability

Watchlist mutations and market-context refresh are admin-key protected.

Market refresh never places broker orders and does not alter scanner signals, paper positions or live-trading permissions.

The existing Render Free SQLite durability limitation still applies. Watchlists and market-context snapshots can disappear after backend redeploy or instance replacement until persistent storage is enabled.
