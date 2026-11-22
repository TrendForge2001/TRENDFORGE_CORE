# Approved TrendForge strategy rules

Owner authorization: “Approved all next strategies. We will deploy paper trading
and backtest every strategies, then decide to keep or change the strategies.”

Registry: `strategy-v16-bullish-scanners-only`.
Execution policy: `approved-horizon-strategies-v2-ema-periods`.

The owner subsequently paused all intraday, short-swing and bearish scanners and
new entries. The current bullish short/long catalog and institutional rating method are in
[SHORT_LONG_INSTITUTIONAL_RATINGS.md](SHORT_LONG_INSTITUTIONAL_RATINGS.md).
Intraday, short-swing and bearish rules below remain historical position-exit references;
they are not current entry choices. Stored positions retain their saved rules.

The owner's subsequent EMA restriction supersedes the former cross-horizon
catalog: intraday uses EMA9/26, swing uses EMA20/50, and EMA50/100 and
EMA100/200 are long-term only. EMA/ADX intraday continuation uses EMA26 for
its price reference. VWMA, RSI, volume, pivot and approved exit rules remain
unchanged. The former Medium-Term EMA50/100 is now Long-Term EMA50/100 with
daily candles, positional history, and its existing yearly exit policy. No
EMA strategy is offered under Medium Term. Stable legacy strategy IDs are
storage identifiers; the displayed names and indicators describe current rules.

Persisted v1 paper positions reconstruct their original horizon and exit rules
and remain monitorable. A v1 plan cannot open a new position. Old registry
validation cannot qualify the revised strategies.

## Common execution rules

- Intraday uses completed **15-minute** candles. Other table horizons use
  completed **daily** candles. A signal never executes at its own closing price.
- Backtests fill at the next observed native candle open with slippage; recheck
  reference/target ordering against the actual fill. Intraday requires the next
  consecutive 15-minute candle in the same session. Cancel invalid fills.
- Paper orders use the first fresh quote observed in the eligible next candle,
  rather than claiming a historical opening fill. Polling, gaps and missing data
  can make forward-paper outcomes differ from historical fills.
- Intraday short simulations require the explicit short-availability assumption.
  Automation honors its saved short-availability switch.
- Only Intraday opens shorts. Bearish strategies in their eligible longer
  horizons produce `EXIT` for an existing long or a scanner stock. An exit-only
  strategy cannot open a stand-alone long/short backtest in that horizon.
- Intraday entries stop before the 15:00 IST square-off; the scanner signal must
  precede 14:30 IST. Automation keeps its existing 14:45 IST entry cutoff.
  Square off all intraday positions at 15:00 IST, including VWMA positions.
- **Every VWMA entry and strategy exit requires RSI14 and Volume SMA20.**
  Long entry: RSI >50; short entry: RSI <50. Long exit: RSI <50;
  short cover: RSI >50. Volume must exceed its current completed-bar SMA20.
  A VWMA reference breach alone never executes a price stop.
- A tick means the configured instrument tick (default research assumption ₹0.05).
  Round protective long references down and short references up. References may
  tighten after a completed candle, effective on the next candle; never widen.
- Reserve full entry notional for either side, do not reuse short proceeds,
  allow at most three simultaneous stocks, and size planned reference risk at
  0.5% of equity including historical transaction costs. Conditional references
  cannot guarantee a maximum loss. Single-share trades are allowed except when
  the annual half-exit needs at least two shares.
- When OHLC cannot establish same-bar order, an active hard stop takes priority
  over profit limits. Completed-candle exits fill at the next open; end-of-test
  liquidation is disclosed separately.

## Individual shorter-horizon rules

| No. | Strategy / horizon | Entry | Target or normal exit | Stop |
|---|---|---|---|---|
| 1 | EMA9/26 Momentum / Intraday | Fresh cross up; close >EMA9 | Completed cross down; next open | Hard stop one tick below trigger low |
| 2 | VWMA9/26 / Intraday long | Fresh cross up, RSI >50, volume >SMA20 | Cross down AND RSI <50 AND high volume | Completed close below active VWMA26 reference AND RSI <50 AND high volume |
| 3 | EMA20/50 / Short Swing or Short Term | Fresh daily cross up, RSI >50, volume >SMA20 | Daily close below nondecreasing EMA20 trail; next open | **Two consecutive post-entry daily closes** below their respective EMA50; reset at/above EMA50 |
| 4 | VWMA9/26 / Short Swing or Short Term | Fresh daily cross up, RSI >50, volume >SMA20 | Daily close <VWMA9 AND RSI <50 AND high volume | Daily close <VWMA26 AND RSI <50 AND high volume |
| 7 | EMA9/26 short / Intraday | Fresh cross down, RSI <50, volume >SMA20 | Completed cross up; next open | Hard stop one tick above the most recent confirmed swing high above actual entry in the preceding 20 candles; skip if absent |
| 8 | VWMA9/26 short / Intraday | Fresh cross down, RSI <50, volume >SMA20 | Cross up AND RSI >50 AND high volume | Completed close above active VWMA26 reference AND RSI >50 AND high volume |
| 9 | Session VWAP breakdown short / Intraday | Previous close ≥its VWAP; current close <its VWAP; consecutive same-session pair; volume >SMA20 | Full fixed target at actual entry −2R; square off at 15:00 | Completed close >current session VWAP; next open |
| 10 | 20-candle low breakdown short / Intraday | Close below preceding 20 lows excluding trigger; volume >1.5× current SMA20 | Tighten hard stop with EMA9 of **HIGH prices** plus one tick | Initial hard stop trigger high plus one tick; lower only after closed candles |
| 11 | EMA/ADX bearish continuation / Intraday | Close <EMA26, ADX14 >25, −DI >+DI | Completed ADX <20; next open | Completed close >EMA26; next open |

For 2/8, initialize the reference one tick beyond signal VWMA26. Raise only for
longs, lower only for shorts; evaluate exits against the previously active
reference before updating it. There is no unconditional intrabar VWMA stop.
For 9, R is signal VWAP plus one tick minus actual short entry; this is a sizing
reference, not a hard stop. For 11, use signal EMA26 plus one tick solely for
sizing. Require positive R and valid positive targets; otherwise skip.

EMA20/50's EMA20 trail remains independent of the two-close EMA50 rule and can
exit earlier. If both trigger on the same candle, report the EMA50 stop reason.
A confirmed swing is strictly above/below two neighbors on **each** side; both
right neighbors must have completed before the trigger candle.

## Pivot-confluence entries and shorter-horizon exits

Fibonacci P=(previous H+L+C)/3; R1/S1=P±0.382(H−L),
R2/S2=P±0.618(H−L), R3/S3=P±(H−L). Use completed prior reference periods.

| Strategies | Intraday entry reference | Other eligible horizon / entry reference |
|---|---|---|
| 12/13 EMA9/26 bullish/bearish pivot | Previous day | Unavailable |
| 14/15 EMA20/50 bullish/bearish pivot | Unavailable | Short Swing or Short Term / previous week |
| 16/17 EMA50/100 bullish/bearish pivot | Unavailable | Long Term / previous week |
| 18/19 EMA100/200 bullish/bearish pivot | Unavailable | Long Term / previous month |

Bullish: fast EMA >slow EMA; low ≤P/S1/S2 <close; green candle.
Bearish: fast EMA <slow EMA; high ≥P/R1/R2 >close; red candle.
Select the qualifying level nearest the signal close. No extra RSI/MACD or
fresh EMA crossover requirement. The optional existing liquidity switch, when
selected, requires volume >1.5× **previous** Volume SMA20.

Freeze the signal reference levels. Recheck all ordering at actual entry.

| No. | Shorter-horizon target | Shorter-horizon stop |
|---|---|---|
| 12 | Full exit at nearest higher frozen pivot above actual fill | Completed close below entry support; next open |
| 13 | Intraday short: full cover at nearest lower frozen pivot | Completed close above entry resistance; next open |
| 14 | Nearest valid target above fill: next frozen pivot or most recent confirmed 20-candle swing high | Completed close below EMA50 OR entry support; next open |
| 15 | Exit signal for existing longs only; no standalone short trade | Resistance rejection in a downtrend produces EXIT |
| 16/18 | Long term only; yearly R1/R2/R3 policy below | Combined yearly-reference stops below |
| 17/19 | Exit signal for existing longs only; no standalone short trade | Resistance rejection in a downtrend produces EXIT |

“Previous swing” uses the same causal 20-candle, two-neighbor definition.
If no eligible target/reference exists, skip entry. Removed intraday variants
remain available only to monitor previously opened v1 positions.

For sizing: 12/13 use one tick outside support/resistance; 14 uses one tick
outside the higher of EMA50 and the anchor. Long-term entries use the second
yearly pivot below the actual fill. These are conditional references, not price stops.

## Long Term annual exits

5: Daily EMA50 crosses above EMA100 AND close >EMA50; Long Term.
6: Daily EMA100 crosses above EMA200 AND close >EMA100; Long Term.
Both now have approved entries and no invented RSI20/MACD filter.

For **5/6 and the long-term bullish pivot entries 16/18**, preserve yearly exits:

1. Freeze the prior completed year's Fibonacci levels at the signal.
2. Require actual long fill below R1. Size against the **second distinct positive
   yearly pivot strictly below actual buying price**; skip if unavailable.
3. Sell floor(original quantity /2) at R1. Trail the remainder toward R2/R3.
   A completed high-volume close above R1/R2 raises the conditional reference.
   A touch of R2 without a high-volume close through it queues a next-open exit;
   otherwise retain the R3 final target.
4. Exit if either complete combined group occurs:
   A: RSI14 <30 AND opening below previous native close;
   B: red candle AND volume >SMA20 AND close below the active conditional support.
   The opening form of A uses only the previous completed RSI and the new open.
   A price-only support breach never exits.
5. Completed bearish setups exit an existing long. No medium/long short entry.

## Separate existing research strategies

The weekly gap-recovery / yearly Floor R2 strategy retains its separate engine.
The daily VWMA20/50 / yearly Fibonacci strategy retains its retest entry and
annual exit map. Its global VWMA revision requires volume confirmation for gap
exits and RSI <50 for the selling-volume support exit. Known-in-advance R1/R3
profit limits qualify using the **previous completed** RSI >50 and volume >SMA20;
R2 close exits/trailing use completed bullish RSI/volume confirmation. Current
candle indicators never retroactively confirm an opening or intrabar fill.
These two remain research-only in their existing dedicated services.

## Deployment and evidence

The registry revision invalidates old promotion evidence. Preserve historical
exit lineage for existing positions, durable storage and owner-only access.
An approved strategy is paper-capable, not automatically performance-qualified.
Fresh registry-matched backtests, Kite authentication, quotes, completed candles,
worker/monitor health and risk checks must pass before paper entries start.
No live broker orders are enabled. Record gross P&L, costs, net P&L, trades,
rejections, date range and actual data coverage; synthetic tests are not market
performance results. Compare real backtests and forward-paper results before
keeping or changing a strategy.

The revised table has 16 standalone strategy/mode pairs, three exit-only
strategies, and two separate dedicated research strategies. The former 23-pair
matrix included EMA combinations in horizons the owner has now removed.
This is a scope change, not a count of passing tests or a performance improvement.

The one-use `run_corrected_research` request starts a fresh full-NIFTY-500
matrix plus the shared-book simulation using the frozen saved paper policy.
It requires authenticated historical reads, completed candles, calculated
indicators, verified storage and paper-only operation; it leaves paper entries
OFF. Historical work does not require current LTP, entry hours or empty paper
position slots. Every paper Start path retains those guards. Short strategies
blocked by the saved admission/availability policy are unmeasured, not losses;
any separate short research must disclose its assumed availability and costs.
The two dedicated research engines require separate backtest requests and
disclosed account/cost bases; the table matrix does not measure them.


## Validation recovery and resource limits

Validation saves every completed stock/mode unit atomically to a private journal
next to the configured database. A restarted job reports interrupted status,
then resumes historical computation after an authenticated startup; this path
never starts paper entries or replays an operator Start request. Completed units
are reused only for matching registry, request and universe membership. Newer
manual validation requests supersede startup recovery.

The original cutoff is frozen; fetches over-read elapsed days and discard bars
after that cutoff. Checkpoints older than seven days require a fresh run.
Validation retains economic fills, selected strategy indicators and fees, while
duplicated execution plans stay out of the aggregate evidence. Rows and final
JSON exports stream from disk, and per-stock reference caches are released after
validation. The normal final report and promotion gates still require every
requested unit; partial/interrupted evidence is never a completed result.

## Private result review

The same explicitly requested, one-use review streams the saved checkpoint in
read-only mode to summarize exit reasons, holding duration, trade economics,
repeat same-day entries, deployment and exposure. It separates stocks with no
trades from losing and flat stocks, and shows breadth/median for stocks that
actually traded alongside the unchanged full-universe promotion gate. Only
registered strategy IDs, fixed exit reason names and aggregate values enter
private Render logs. It never enables entries or relaxes validation thresholds.

An explicitly authorized, one-use `review_validation` operator request reads a
completed current-registry snapshot and checks paper readiness. It cannot start
validation, enable paper entries, or submit orders. The private Render logs contain
only registered strategy IDs, allowlisted aggregate backtest metrics and gate
names; symbols, trades, account details, credentials and provider errors are
excluded. Gross P&L is net P&L plus transaction costs, with modeled slippage already
reflected in fills. Each strategy uses independent capital per symbol; aggregate
test results must not be described as one shared-capital portfolio return.

The review also reads journal errors in SQLite read-only mode and reports counts
under fixed failure categories. Raw error text, symbols and account/provider
details remain private in the journal; diagnostic review never deletes or retries
saved work.

Regular-weekday intraday simulations still require an observed 15:00 IST candle.
Approved entry rules already exclude weekends and out-of-hours fills. Their
observed session prices remain available to indicators without requiring a
fictitious square-off event on a date that cannot open a position. This includes
Sunday Muhurat bars starting at 14:20 IST, as documented in the
[2026 broker schedule](https://zerodha.com/marketintel/bulletin/461711/muhurat-trading-session-on-account-of-diwali-november-2026/).
Native fills remain limited to 09:15–15:00 IST, with normal positions squared off
at 15:00. Missing regular-weekday square-off candles still reject the simulation.

An explicit `retry_failed` validation request keeps the original request, run ID,
as-of cutoff and successful checkpoint units. Failed units are atomically
requeued, and the complete report is rebuilt after processing. A durable pending
retry marker survives a restart before deletion. Retry is historical work only;
the one-use `retry_failed_validation` operator action cannot arm paper entries.
