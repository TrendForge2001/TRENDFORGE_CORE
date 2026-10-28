# Six source pairs plus five requested intraday short strategies

The original six source-derived definitions below remain active. The owner
subsequently requested intraday short selling; the catalog also includes the
EMA 9/20 and VWMA 9/26 SHORT counterparts described in
[the short-strategy rules and session checklist](INTRADAY_SHORTS_SESSION_READINESS.md).
Three additional short pairs are documented in
[SHORT_SCANNERS_AND_PAPER_DIAGNOSTICS.md](SHORT_SCANNERS_AND_PAPER_DIAGNOSTICS.md).
The total active catalog is eleven, with nine executable and two review-only.
The new short definitions use source `user_analysis`, not `user_notebook`.

The retained source definitions are:

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
strategy has a matching scanner selection. Retired composite/template
strategies remain excluded.

Medium/long-term source notes leave momentum confirmation, staged targets and
protective stops insufficiently defined. Both definitions remain visible under
Medium / Long term, with no numeric score, simulated entries or executable
backtest until reviewed. Their registry `paper_eligible` flag is false.

The four executable source choices retain their documented entry rules and
limitations; intraday targets now use 2R, meeting the notebook's 1.5R minimum
and the paper admission floor. The five short pairs have explicit
bearish rules. No candle intervals or broker permissions change. Validation, risk,
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
