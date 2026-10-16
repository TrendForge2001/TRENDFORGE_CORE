# R67.3 — Correction-Aware Scanner Eligibility

R67.3 separates scanner analysis/ranking from execution eligibility so TrendForge remains informative during market corrections while paper execution remains fail-closed.

## Motivation

R67.2 production validation showed that a correction can legitimately suppress actionable long entries while still leaving useful relative-strength information in the scan.

The observed 100-symbol validation had:

- 98 Fundamental Engine failures, primarily incomplete fundamental inputs;
- 52 Market Regime Engine failures, predominantly RISK_OFF;
- 3 Risk Engine failures;
- 0 legacy execution-eligible top picks.

Under the pre-R67.3 contract, the same strict gate controlled both ranking and execution. A stock blocked by market regime, a mandatory decision threshold, or a non-BUY final signal disappeared from scanner ranking even when its analysis completed successfully.

## Dual-gate contract

R67.3 adds two explicit gates.

### Gate 1 — Analysis / ranking

A symbol remains analysis-eligible when the scanner completed a trustworthy analytical result.

The analysis gate rejects only structural failures that make ranking unreliable:

- pipeline errors;
- engine execution exceptions;
- missing mandatory engine results;
- final ERROR signals.

The analysis gate does **not** reject a symbol merely because:

- the market regime is RISK_OFF;
- a mandatory engine's decision threshold failed;
- the final signal is HOLD, REDUCE, or SELL;
- fundamentals are present but incomplete/insufficient for the strict execution decision;
- a hard-risk veto blocks execution.

This permits correction-aware relative-strength ranking without implying permission to trade.

### Gate 2 — Execution

The execution gate preserves the existing strict R67.2 behavior.

Execution remains blocked when any existing rejection condition is present, including:

- orchestrator failure;
- HOLD / SELL / REDUCE / IGNORE / ERROR final signals;
- hard-risk blocks;
- mandatory engine failure;
- mandatory engine result missing;
- engine execution error;
- pipeline error.

The legacy fields remain execution-gated for backward compatibility:

- `eligible`
- `rejection_reason`
- `rejection_reasons`
- `results`
- `top_picks`
- `count`
- `rejected`
- `rejected_count`

## New R67.3 fields

Per-symbol:

- `analysis_eligible`
- `analysis_rejection_reason`
- `analysis_rejection_reasons`
- `execution_eligible`
- `execution_rejection_reason`
- `execution_rejection_reasons`

Batch-level:

- `analysis_ranked`
- `analysis_top_picks`
- `analysis_eligible`
- `analysis_rejected`
- `analysis_count`
- `analysis_rejected_count`
- `execution_eligible`
- `execution_top_picks`
- `execution_rejected`
- `execution_count`
- `execution_rejected_count`
- `eligibility_semantics_version = R67.3`

## Paper auto-entry safety

R67.3 does not loosen R67.2 execution.

Paper auto-entry explicitly consumes `execution_top_picks` when that field is present and falls back to legacy `top_picks` only for older scanner payloads.

Candidate evaluation also reads `execution_eligible` first, with legacy `eligible` as the compatibility fallback.

Therefore:

```text
analysis_top_picks
    -> monitoring / relative-strength ranking / watchlist

execution_top_picks
    -> R67.2 risk-governed paper-entry evaluation
```

An analysis-only candidate cannot become a paper order merely because it ranks highly.

## Webapp behavior

The Scanner page prefers `analysis_top_picks` for the ranked-candidate table.

Each row exposes:

- Analysis Eligible
- Execution Eligible
- Execution Block

The "Execution eligible only" toggle reduces the table to actionable candidates without discarding the correction-aware ranking by default.

## Example correction behavior

A symbol can now produce:

```text
Signal: HOLD
Market Regime: RISK_OFF
Fundamental state: INCOMPLETE
Analysis Eligible: true
Execution Eligible: false
```

It remains visible in scanner ranking, but R67.2 cannot open a paper trade from it.

## Safety invariant

R67.3 changes scanner observability and ranking semantics only.

It does not:

- enable live broker orders;
- bypass hard-risk vetoes;
- bypass the market-entry time window;
- lower paper auto-entry score/confidence thresholds;
- weaken daily loss, position-count, reward/risk, duplicate-symbol, or sizing controls.

Real broker execution remains independently disabled unless explicitly enabled by the existing live-trading controls.
