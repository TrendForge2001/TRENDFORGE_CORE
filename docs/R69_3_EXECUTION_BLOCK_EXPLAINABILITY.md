# R69.3 — Execution Block Explainability & Fundamental Readiness

R69.3 makes R67.3 execution decisions operationally explainable without
changing any scanner eligibility rule.

R67.3 remains the canonical two-gate contract:

- analysis/ranking eligibility;
- strict execution eligibility.

R69.3 adds diagnostics only.

## Why this batch exists

The R67.3 production verification correctly ranked correction-phase stocks
while keeping all tested candidates execution-ineligible. However, the primary
legacy rejection value was often only:

`orchestrator_failed`

That is safe but not actionable. It does not identify whether the candidate is
blocked by market regime, fundamental data readiness, fundamental quality,
risk, or a non-actionable final signal.

## Per-symbol execution diagnostics

Every scanner result now exposes:

- `primary_execution_block`
- `execution_block_reasons`
- `fundamental_readiness`
- `market_regime_context`
- `risk_context`

The legacy fields remain unchanged:

- `eligible`
- `execution_eligible`
- `execution_rejection_reason`
- `execution_rejection_reasons`
- `rejection_reason`
- `rejection_reasons`

Therefore R67.2 paper auto-entry and R67.3 fail-closed behavior do not change.

## Fundamental readiness

R69.3 distinguishes data readiness from fundamental quality.

Possible statuses:

### READY_PASS

All required numeric fundamental inputs are valid and the Fundamental Engine
passes its quality threshold.

### READY_FAIL_QUALITY

All required numeric inputs are valid, but the company fails the configured
fundamental quality threshold.

This is a quality decision, not a data-coverage failure.

### NM_READY

Validated N/M evidence supports the existing evidence-aware scoring path, such
as EPS growth being mathematically non-meaningful with accepted provenance.

`quality_pass` still reports whether the resulting fundamental score passes.

### DATA_INCOMPLETE

The Fundamental Engine cannot perform a fully eligible fundamental decision
because required data is missing or readiness evidence is incomplete.

Missing fields are exposed through:

`fundamental_readiness.missing_fields`

### INVALID

Fundamental values were supplied but failed the strict numeric contract.

Invalid fields are exposed through:

`fundamental_readiness.invalid_fields`

### MISSING

No Fundamental Engine result is available.

## Specific execution blockers

Examples include:

- `fundamental:data_incomplete`
- `fundamental:invalid_data`
- `fundamental:quality_failed`
- `fundamental:quality_failed_nm`
- `market_regime:risk_off`
- `market_regime:failed`
- `risk:failed`
- `risk:hard_block`
- `hard_block:<engine>`
- `mandatory_missing:<engine>`
- `mandatory_failed:<engine>`
- `engine:execution_error`
- `pipeline:error`
- `signal:hold`
- `signal:reduce`
- `signal:sell`
- `signal:ignore`
- `signal:error`

The first item becomes `primary_execution_block`; the full list preserves all
identified blockers.

## Market-regime context

Each result exposes:

- pass/fail;
- regime;
- direction;
- score;
- explicit `risk_off` flag;
- warnings.

A `RISK_OFF` regime continues to block strict long execution when the
mandatory Market Regime Engine fails. R69.3 does not weaken this protection.

## Risk context

Each result exposes:

- pass/fail;
- hard-block flag;
- risk score;
- reward/risk ratio;
- entry;
- stop loss;
- quantity;
- warnings.

Risk failures continue to block execution.

## Batch diagnostics

Scanner batch responses now include:

`execution_explainability_version = R69.3`

and:

```text
eligibility_diagnostics
  execution_block_counts
  fundamental_readiness_counts
  market_regime_counts
```

This makes it possible to distinguish a market-wide correction from a
fundamental-data coverage problem in one response.

## Compact API

`compact=true` symbol rows retain lightweight versions of:

- primary execution block;
- execution block reasons;
- fundamental readiness;
- market regime context;
- risk context.

## Webapp

The Scanner ranked-candidate table now shows:

- Execution Block
- Fundamental Readiness
- Market Regime
- Risk R:R

An execution-diagnostics expander also summarizes blocker counts,
fundamental-readiness counts and market-regime counts.

## Safety invariant

R69.3 changes explainability only.

It does not:

- change R67.3 analysis eligibility;
- change R67.3 execution eligibility;
- change R67.2 paper auto-entry candidate selection;
- lower BUY/STRONG BUY thresholds;
- bypass Market Regime;
- bypass Fundamental or Risk mandatory gates;
- enable live broker orders.

R67.3 remains fail-closed for execution.
