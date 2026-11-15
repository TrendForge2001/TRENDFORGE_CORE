# Research failure diagnosis — 15 November 2026

The reported NIFTY 100 requests ended with `research_batch_failed`. The web
service remained live; sampled memory during the two reported attempts was
approximately 299 MiB against its 512 MiB limit. The original isolated worker
suppressed all logs and discarded stderr, leaving no exception location or
useful action in the persisted batch. A successful synthetic suite did not
establish the cause of these production failures.

Workers now persist fixed error codes plus bounded diagnostic metadata: phase,
exception class, project-relative filenames/line numbers and a stable reference.
Exception messages, locals, source lines and provider response bodies are never
included. Failures constructing the provider/technical service are caught too.
The parent emits only that sanitized metadata in Render logs. Reports distinguishes
Kite authentication, absent usable history, candle budgets and invalid accounting.
Existing batches and archived reports remain intact; old failures without metadata
are not assigned a fabricated diagnosis.

An optional `TRENDFORGE_RESEARCH_RETRY` JSON operator intent can replay one failed
weekly request on the original Render service. It requires an explicit unique
request ID, accepts a failed batch ID or `latest_failed_weekly_nifty100`, and
copies only that request's stocks, strategy, horizon, list and period. The new
batch records `retry_of`; the original is preserved. A durable SQLite claim is
committed before submission. The same request ID is consumed across restarts,
even if submission is interrupted; another retry needs a deliberate new intent.
No intent means no replay. Other services and PC clones ignore the setting.
The normal workload gate, bounded queue, isolated worker and disabled order
flags still apply. It cannot replay scans, completed work or real broker orders.

The one-time replay is for diagnosing the user's failed historical request,
not daily scheduling or automatic recovery. Its outcome and report checksum are
logged without credentials. A failure caused by an expired Kite session still
requires owner authentication; the application cannot manufacture a new token.
