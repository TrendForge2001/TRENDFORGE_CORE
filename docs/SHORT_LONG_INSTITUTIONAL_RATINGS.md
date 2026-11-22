# Short-term and long-term scanners with institutional ratings

Registry: `strategy-v15-short-long-institutional-ratings`.

The owner paused intraday and short-swing strategies. New scanner choices,
historical jobs and paper entries exclude those horizons. Nine intraday strategy
IDs remain readable for stored positions and historical lineage, with paper
eligibility disabled. Existing intraday and short-swing positions keep their
saved exit policy; this change does not close positions or start automation.

The current catalog has 12 strategies: five Short Term and seven Long Term.
Three bearish pivot strategies supply exit signals for existing longs and scanner
stocks. They cannot open shorts. Medium Term remains reserved until the owner
defines separate rules. Short Term uses daily EMA20/50; Long Term retains the
approved EMA50/100 and EMA100/200 setups. Approved entry, target and stop rules
within these active horizons are unchanged.

| Short Term | Long Term |
| --- | --- |
| EMA20/50 + RSI + Volume | Weekly EMA50/100 gap recovery / yearly floor |
| VWMA9/26 + RSI + Volume | EMA50/100 crossover |
| EMA20/50 bullish pivot | EMA100/200 crossover |
| EMA20/50 bearish pivot (exit only) | EMA50/100 bullish pivot |
| Daily VWMA20/50 yearly Fibonacci | EMA50/100 bearish pivot (exit only) |
| | EMA100/200 bullish pivot |
| | EMA100/200 bearish pivot (exit only) |

## Rating method

`institutional-technical-rating-v1` is an explainable screening score, not a
probability, validated return forecast or order-admission policy. It is displayed
alongside the original strategy signal and never replaces that signal, alters
position exits, ranks paper candidates or places orders.

Institutional points are `40 × average buying / (average buying + average
selling)`. Each average is per investor on that trade side, following the owner's
approved comparison. Use either actual disclosed share quantities or actual
traded INR values consistently. Equal zero means receive 20 points only when
there are valid observations. Quarterly holdings and ownership changes cannot
stand in for actual trades. Unreported transactions remain unknown.

| Technical component | Points |
| --- | --- |
| EMA and VWMA trend | 20 bullish; 0 bearish; 10 mixed |
| Wilder RSI14 | 15 for `50 < RSI <= 70`; 0 below 50; 7.5 otherwise |
| Daily volume versus SMA20 | 15 above; 0 otherwise |
| Previous-year Fibonacci pivot | 10 above P; 5 above S1 but not P; 0 otherwise |

Short-term bullish trend requires `close > EMA20 > EMA50`; long-term bullish
trend requires `close > EMA50 > EMA100 > EMA200`. Both also require
`close > VWMA20 > VWMA50`. The bearish trend reverses these comparisons.
Bullish confirmation additionally requires `50 < RSI14 <= 70` and volume above
SMA20. Bearish confirmation requires RSI14 below 50 and volume above SMA20.
VWMA lines alone cannot confirm either direction.

| Rating | Required evidence |
| --- | --- |
| STRONG_BUY | Actual average buying exceeds selling, bullish technical confirmation, total at least 80 |
| BUY | Same agreement, total at least 65 but below 80 |
| EXIT | Average selling exceeds buying and bearish technical confirmation; existing longs only |
| CONFLICT | Buying with bearish technicals, or selling with bullish technicals |
| HOLD | Equal actual averages and neutral technicals |
| WATCH | Complete evidence without the agreement required above |
| INSUFFICIENT_DATA | Missing, invalid, stale or future-dated evidence |

Ratings require a complete actual-flow input window ending no more than seven
calendar days ago, valid source dates and completed daily technical evidence from
the latest configured market session. There is no partial score when either side
is missing. Future disclosures, first-seen times and candles are excluded.
Official disclosure time remains blank when the source does not supply it; an
observation timestamp is not presented as publication time. A rating produced now
cannot be reused as historical evidence that was known at an earlier time.

## Where evidence appears

- Institutional Scanner: select Short Term or Long Term, check completed daily
  evidence, filter ratings and inspect the component values, source coverage and
  disclosure time.
- Technical Scanner and its CSV/Excel reports: original technical entry/exit
  signal plus separate institutional rating, score, reason and evidence dates.
  Scans reuse the owner's locally stored disclosures and already-fetched candles;
  they do not publish portfolio data or refresh external institutional sources.
- Private workbook export: `STOCK RATINGS` contains both horizons;
  `RATING METHOD` records the weights and thresholds. Imports still recompute
  actual activity and do not trust a spreadsheet's cached rating.

The new registry version invalidates older promotion evidence. A new validation
must cover the active modes (`swing`, `positional`) and the saved account policy.
Historical compatibility tests deliberately replay frozen older catalogs; current
scope, restoration and rating tests separately exercise the present restrictions.
No market performance or live feed coverage is established by these correctness
tests. This change has not been deployed to Render.
