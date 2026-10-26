# Six source-derived scanner / strategy pairs

The active catalog, webapp selection and saved-strategy automation now use only:

| Pair | Candle interval | Status |
|---|---|---|
| Intraday EMA 9/20 Momentum + RSI/Volume | 15 minutes | Existing deterministic evaluator |
| Intraday VWMA 9/26 + RSI/Volume | 15 minutes | Existing deterministic evaluator |
| Swing EMA 20/50 + RSI/Volume | Daily | Existing deterministic evaluator |
| Swing VWMA 9/26 + RSI/Volume | Daily | Existing deterministic evaluator |
| Medium-Term EMA 50/100 | Daily / weekly source context | Review required |
| Long-Term EMA 100/200 | Daily / weekly source context | Review required |

These six are drawn from the supplied source summary. The earlier recommended
five horizon groups are a classification, not five fully specified algorithms;
the two distinct intraday setups are kept as separate pairs. Each retained
strategy has a matching scanner selection. No seventh composite momentum choice
or template strategy is offered.

Medium/long-term source notes leave momentum confirmation, staged targets and
protective stops insufficiently defined. Both definitions remain visible under
Medium / Long term, with no numeric score, simulated entries or executable
backtest until reviewed. Their registry `paper_eligible` flag is false.

The four executable choices retain the existing deterministic rules and their
existing documented limitations. This change does not invent notebook rules,
change candle intervals or activate real broker orders. Validation, risk,
storage, time-window and kill-switch gates still apply to paper entries.

Retired identifiers are excluded from active registry detail/list/readiness,
new scans, backtests and new paper-entry admission. Legacy technical HTTP
requests that omit a strategy use the first active pair for the selected mode.
Browser scan caches for retired/composite IDs are invalidated on page load.

Historical backtests and paper P&L records are not deleted. Retired position
lineage has a private exit-only compatibility path: it can return EXIT or HOLD,
never BUY. It is not an active scanner, does not admit new positions, and is
not advertised by readiness. Existing manual/ATR/kill controls remain usable.
Historical reporting can retain retired strategy rows as unregistered history.
