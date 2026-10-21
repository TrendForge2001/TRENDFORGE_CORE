# R72.5.4 — Strategy-Driven Paper Trading

R72.5.4 connects the R72.5 multi-strategy scanner and R72.5.3 validation
results to the existing canonical R67.2 paper auto-entry gate.

## Safety boundary

This batch is paper-only.

It does not:

- place Kite or broker orders;
- bypass the paper-trading kill switch;
- bypass R67.2 score, confidence, reward/risk, position-sizing, duplicate,
  daily-loss or market-hours controls;
- automatically promote a backtested strategy;
- execute positional strategies, because the canonical paper runtime currently
  supports intraday and swing modes only.

Every actual simulated entry still flows through:

```text
R72.5.2 multi-strategy scanner
-> R72.5.3 validation eligibility
-> R72.5.4 strategy/lineage selection
-> R67.2 PaperAutoEntryService
-> PaperTradingService
-> SQLite paper trade
-> paper quote monitor / SL / target / intraday 15:00 exit
```

Broker orders remain hard-disabled in this path.

## Required lineage

Preview and execution require three explicit identifiers:

- `strategy_id`
- `scan_run_id`
- `validation_run_id`

The requested scanner run must still be the latest saved multi-strategy result,
must have completed with zero symbol errors, and must have completed every
requested symbol.

The requested validation run must still be the active completed R72.5.3
validation result.

This prevents a UI refresh or race from silently executing against different
scanner or validation evidence.

## Strategy eligibility

A strategy can enter the R72.5.4 preview only when:

1. it exists in the canonical registry;
2. the registry marks it `paper_eligible=true`;
3. the scanner mode is `intraday` or `swing`;
4. the strategy was evaluated as `BUY` for the candidate;
5. the candidate consensus is `BUY` or `STRONG_BUY`;
6. R72.5.3 reports `promotion_status=ELIGIBLE_FOR_REVIEW`;
7. the scanner universe has a `PASS` gate in the validation evidence;
8. R67.2 auto-entry is enabled;
9. canonical paper trading is enabled and the kill switch is open.

`ELIGIBLE_FOR_REVIEW` is therefore necessary but not sufficient for a paper
position.

## Risk evidence

R72.5.2 scanner results now retain each BUY strategy's own:

- `paper_eligible` flag;
- entry;
- stop loss;
- target;
- strategy score.

R72.5.4 uses the selected strategy score as the R67.2 score input and the
multi-strategy consensus score as the R67.2 confidence input.

R67.2 remains the sizing authority. Scanner quantity, if any, is not trusted.

## Duplicate execution protection

For one application instance, the tuple:

```text
(scan_run_id, validation_run_id, strategy_id)
```

may be submitted for execution only once.

The existing paper repository also continues to block duplicate open symbols
and repeat trading of the same symbol on the same IST trading date.

## API

Read-only readiness:

```text
GET /paper/strategy-driven/readiness
```

Admin-gated preview:

```text
POST /paper/strategy-driven/preview
```

Admin-gated paper execution:

```text
POST /paper/strategy-driven/execute
```

Request body:

```json
{
  "strategy_id": "tpl_supertrend_rsi",
  "scan_run_id": "r7252-...",
  "validation_run_id": "r7253-..."
}
```

Preview does not create a position. It shows lineage blockers, matching
candidates and the current R67.2 approval/rejection evidence.

Execution re-evaluates the R67.2 gate immediately before delegating to the
canonical paper auto-entry service.

## Streamlit

The Technicals page adds an R72.5.4 section that:

- shows strategy-paper readiness;
- lists validation-eligible strategies matching the latest scanner mode;
- previews R67.2 approval, quantity and rejection reasons;
- requires an explicit confirmation checkbox;
- submits the exact scan and validation run IDs;
- links to the separate Paper Portfolio page.

## Production rollout

Deploy R72.5.4 without changing existing safety environment variables.

The feature remains blocked unless the existing paper controls permit opening
positions, including:

```text
TRENDFORGE_PAPER_TRADING_ENABLED
TRENDFORGE_PAPER_TRADING_KILL_SWITCH
TRENDFORGE_PAPER_AUTO_ENTRY_ENABLED
```

No live-trading environment variable is changed by this batch.
