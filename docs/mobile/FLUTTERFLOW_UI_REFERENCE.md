# FlutterFlow UI reference: Streak examples, TrendForge analysis

## Source boundary

The owner explicitly clarified that the supplied Streak Home, Discover Live
Scanners and Discover Strategies screenshots illustrate how the application
should look and behave. They are not a source of trading algorithms.

- Use the examples for information hierarchy, search/filter placement,
  list/detail navigation, chart placement, results presentation and action bars.
- Populate scanners, strategy names, indicators, conditions, scores and
  entry/exit/risk rules from the owner's TrendForge analysis and approved backend
  registry. Never seed the app with presets extracted from these screenshots.
- Keep TrendForge branding. Screenshot account values, prices, performance
  figures and notifications are not app data or calculated results.
- Preserve the current analysis-derived catalog and execution eligibility.
  A visual redesign must not change an algorithm, activate a review-only rule
  or authorize broker orders.

## Home example -> Watchlist and overview

Use a compact market ticker strip, portfolio/automation overview, stock chart,
watchlist and recent scanner results. On a phone, stack these sections rather
than compressing the desktop screenshot into a miniature three-column page.

The overview distinguishes simulated capital/P&L from authenticated broker
holdings. Selecting a watchlist stock changes the stock detail/chart context.
Scanner previews deep-link to that scanner's results with its actual strategy
ID, universe, timeframe and observation timestamp. Show source and freshness;
missing market data is unavailable, not a zero price. Paper and live broker
positions must have separate labels and totals.

## Live Scanners example -> Scanner catalog and results

Use search, timeframe/category filters and the Nifty universe dropdown above a
scrollable catalog. Each item shows the owner's scanner name, timeframe,
indicator summary and eligibility state. Phone navigation opens a dedicated
detail/results screen; larger layouts may use side-by-side catalog and detail.

The detail screen includes View Conditions, selected universe, last completed
scan time, a Run Scan action and results. Stock rows show symbol, available quote
and change, individual stock score, signal and data status. Conditions are read
from the backend definition, not inferred from a screenshot label.

Rows support stock details and selection. A contextual bottom action bar offers
Backtest selected stocks and Paper trade selected stocks when the backend and
eligibility permit them. Do not turn the reference's B/S icons into immediate
broker-order buttons. New entries require existing server-side checks and a
deliberate operator command.

## Strategies example -> User strategies and backtest P&L

Use a searchable strategy catalog with mode/timeframe badges and a selected
strategy detail view. Show the owner's actual indicator/condition summary and
offer a route to the full rules. In the existing five-workspace navigation this
catalog is a child view of Backtesting, also reachable from scanner details.

The results view uses a Cumulative selection followed by individual-stock chips,
summary metrics, trade ledger and equity/P&L charts. Daily summaries and monthly
performance tiles may follow the screenshot's arrangement, but every value must
come from completed backtest evidence with disclosed costs and allocation
assumptions. The current shared portfolio uses ₹1,00,000 total capital, at most
₹80,000 committed including entry fees, a ₹20,000 reserve and three concurrent
stocks. New-entry budgets are proportional to eligible signal scores. See
[the execution policy](../THREE_STOCK_PORTFOLIO.md). Legacy independent stock
allocations must not be presented as this shared portfolio.
Do not derive cumulative return by adding stock return percentages.

Retain scanner snapshot/strategy provenance and the existing warning about
selecting today's scanner matches for historical tests. Show partial failures
and unavailable metrics explicitly. Never fill empty panels with screenshot
profits, sample signals or invented trades.

## FlutterFlow component plan

| Reusable component | Binding / behaviour |
|---|---|
| MarketTickerStrip | Available index quotes, change and freshness |
| PortfolioSummary | Explicit Paper or Broker context; real backend totals |
| UniverseSelector | Official supported Nifty membership and sector filters |
| ScannerStrategyItem | Backend ID, name, interval and eligibility |
| IndicatorChips / ConditionsSheet | Approved backend definition |
| StockResultCard | Symbol, quote, score, signal, timestamp and selection |
| BacktestMetrics / StockSelector | Completed result metrics and per-stock drill-down |
| EquityPnlChart / MonthlyPerformance | Actual equity/trade observations; gaps remain visible |
| PaperAutomationControls | Confirmed server state, target scope, blockers and explicit Start/Stop |
| LoadingEmptyErrorStaleState | Consistent network/data-state presentation |

Use the existing TrendForge dark palette and readable text; reuse the reference
layout rather than its branding. Keep phone controls comfortably tappable and
support scrolling, larger fonts and wide-screen list/detail layouts. Preserve
the five destinations: Watchlist, Scanner, Backtesting, Paper Trading and Kite
Session; use child screens and bottom sheets for settings and details.

Create/Edit Scanner and Create/Edit Strategy are future capabilities until
versioned user-definition persistence, input validation and evaluator support
exist. A visual button must not imply that an unsupported rule can be saved or
traded. The current registry remains authoritative.

## Design acceptance

1. Compare the three reference layouts with their corresponding mobile flows,
   including search, filtering, stock selection and backtest drill-down.
2. Check every displayed scanner/strategy against the approved TrendForge
   registry; there must be no imported Streak presets or screenshot data.
3. Confirm the redesigned UI produces the same strategy IDs, parameters and
   results as the existing backend for the same inputs.
4. Verify loading, empty, partial failure, stale, authorization and blocked-entry
   states without fabricated prices or performance.
5. Verify all trade dates/times in IST and distinct Paper/Broker context.

This brief is a specification, not an exported FlutterFlow project or a built
Android screen. See [the development handoff](../FLUTTERFLOW_MOBILE_HANDOFF.md)
for implementation batches and outstanding project access.
