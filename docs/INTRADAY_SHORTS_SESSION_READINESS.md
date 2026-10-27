# Intraday short paper trading and compact workspace

Target preparation: the next NSE session after 27 October 2026 (28 October,
subject to the exchange calendar). This is an implementation and operating
checklist; repository tests do not establish that the owner's PC is running
the new release or that tomorrow's Kite session is authenticated.

## Strategies

The six retained source definitions remain, plus two explicitly requested
bearish counterparts. These are TrendForge `user_analysis` rules, not source
image transcriptions or Streak presets:

| Strategy | Completed 15-minute entry checks | Cover/exit checks |
|---|---|---|
| `tf_intraday_ema9_20_short` | EMA9 crosses below EMA20; RSI14 ≤ 40; volume > volume SMA20; signal bar starts at/after 09:45 IST | Bullish EMA crossover, RSI14 ≥ 60, protective stop, target or 15:00 square-off |
| `tf_intraday_vwma9_26_short` | VWMA9 crosses below VWMA26; close within 1% of VWMA9; RSI14 ≤ 40; volume > volume SMA20; signal bar starts at/after 09:45 IST | Bullish VWMA crossover, RSI14 ≥ 60, protective stop, target or 15:00 square-off |

For both: stop = entry + 1.5 × ATR; target = entry − 2 × risk/share. Invalid,
missing or nonpositive brackets cannot enter. Short entries are intraday only.
Signals use completed candles, so a 09:45-start candle is actionable only after
its 10:00 close. Automation admits entries before 14:45 IST. Short covers use
fresh Kite quotes; no broker order is submitted.

The retained intraday long evaluators now produce 2R targets, satisfying the
source minimum of 1.5R and the default paper admission minimum of 2R. Swing
targets remain 2R. The registry version changed, so cached validation for the
previous catalog cannot approve this release; rerun full-universe validation.
Validation can reject a strategy. A failed historical gate is not bypassed.

## Signal meanings

- **BUY:** a new long setup; separate paper admission is required.
- **SELL:** a new short setup under a registered intraday short strategy.
- **WAIT:** no current entry. Old cached neutral HOLD scanner rows display WAIT.
- **EXIT:** a strategy exit condition, not an instruction to open a short.
- **HOLD:** an existing paper position or delivery holding. The exit-only
  evaluator can emit HOLD; flat scanner evaluation cannot.
- **REVIEW_REQUIRED / ERROR:** incomplete rules or unavailable data; no entry.

Opposing entry directions in one multi-strategy evaluation produce CONFLICT
and no primary entry candidate. Scores are check-completion percentages,
not predictions or probabilities of profit.

## Capital and accounting

Shared portfolio backtests keep ₹1,00,000 initial capital, ₹80,000 maximum
entry collateral (including entry fees), ₹20,000 reserve and at most three
concurrent stocks. Entries split available budget in proportion to their
scores and use whole shares. A short commits its full entry notional; sale
proceeds are not added to buying power. Equity equals free cash plus reserved
collateral and unrealized directional P&L. Short fills sell with adverse
slippage and buy to cover with adverse slippage. Both sides pay configured
transaction costs. Stops win bars touching both stop and target; adverse gaps
use the open. Missing required 15:00 evidence rejects an intraday result.

Automated paper entries share the same collateral pool across long and short
positions. Their maximum notional is 80% of configured paper capital; 20% is
reserved. Realized losses reduce available entry capital; profits do not raise
the cap. Per-trade risk, daily loss, duplicate-symbol, position-count, market,
validation, fresh-data, storage and kill gates still apply. The PC launcher
defaults to three positions unless an explicit existing environment override
sets another count. The short signal must carry registered short-strategy
lineage and intraday mode; generic SELL/EXIT strings cannot create a short.

Paper statements currently show **gross simulated P&L, excluding costs and
slippage**. Cost-adjusted backtest P&L is a separate result; do not compare
them as equivalent net-return figures.

If the PC sleeps, loses connectivity or stops, continuous monitoring cannot be
guaranteed. Restored intraday positions from an earlier date exit on the next
available monitored quote with MISSED_INTRADAY_SQUARE_OFF. This preserves the
actual recovery fill; it never fabricates a fill at yesterday's 15:00 price.

## Workspace layout

The five existing top-level workspaces remain. Each has a compact left control
panel and a wider right data panel, with bounded independent scrolling. Stock
lists, indicators, positions and result tables are on the right; selectors,
forms, Start/Stop and exports are on the left. The sidebar is collapsed by
default. Narrow mobile screens stack the panels without horizontal page
overflow. Expand advanced controls when required. Browser tests use fixtures,
not live market data. Refresh paper readiness/positions explicitly; background
server monitoring continues independently of the page's refresh rate.

## PC update and pre-session checks

1. Preserve the existing `%LOCALAPPDATA%\TrendForgeCore` directory, including
   database, private credentials and paired storage proof. Use the existing
   SQLite backup command before replacing an installation. Never delete or
   reset the book to clear a startup blocker.
2. Stop the original launcher with Ctrl+C. Extract the latest reviewed `main`
   into a new release folder and launch its `Start-TrendForgePaper.ps1`, using
   the same default data directory. Merely refreshing an old PC webapp does
   not install GitHub/Render changes.
3. Refresh the daily Kite access token privately when required. `-CheckKite`
   must show profile_authenticated=true, quotes_available=true and status=ready.
4. The updated PC launcher enables quote and strategy-exit monitoring. It
   retains loopback binding, one-process locking, restart-verified storage and
   disabled real broker execution. Automation remains OFF after restart.
5. Open `/app/`. Confirm verified storage, restored positions, working Kite
   session/quotes and no monitor error. A storage banner alone is insufficient.
6. Under Live Paper Trading, expand **Prepare strategy validation before the
   session**, select **Validate saved strategies**, then **Check validation
   progress**. This validates the full configured Nifty universe without
   arming new entries. Inspect each strategy's gate and resolve provider errors.
7. In Technical Scanner, choose Intraday and the intended long or SHORT
   strategy, a Nifty list/sector, and run a scan. Inspect each candidate's
   indicator values, stop, target, risk:reward and candle time. WAIT/EXIT rows
   cannot arm an entry through the scanner handoff.
8. Start selected-stock paper trading or the saved-strategy automation only
   after the running backend reports no blockers. Check automation phase,
   last cycle and open positions during the session. Start arms the worker;
   it does not guarantee a qualifying trade.
9. Keep the PC plugged in, awake, network connected and the launcher open.
   Stop blocks new entries while monitored exits continue. Killing the Python
   process also stops monitoring. Keep real broker execution disabled.

## Verification boundary

Automated coverage includes bearish crossover/indicator checks, WAIT/HOLD
semantics, scanner SELL lineage, short next-open fills, cover slippage/costs,
stop-first and gap outcomes, full collateral with proportional top-three
allocation, durable short restoration/P&L, square-off recovery, invalid bracket
and overnight rejection, shared long/short buying power, withdrawn admission,
old-catalog validation rejection and existing Start/Stop/broker write guards.
Live PC startup and next-session execution still require the checks above.

Release validation: 2,168 tests passed and four platform-dependent tests skipped
locally; all five active screens and the paper/backtest result selectors passed
fixture-based Chromium checks at desktop and Android-sized widths, with no
runtime exceptions, horizontal page overflow or action buttons on the right.
All 68 locked dependencies passed the vulnerability audit. The complete Git
history/current-file secret scan passed with zero unreviewed findings.
