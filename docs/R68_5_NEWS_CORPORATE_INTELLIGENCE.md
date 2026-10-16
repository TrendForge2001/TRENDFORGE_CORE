# R68.5 News and Corporate Actions Intelligence

R68.5 adds a canonical persisted evidence layer for symbol-scoped news and corporate actions, together with dedicated Streamlit dashboards.

## API contracts

Read-only:

    GET /intelligence/readiness
    GET /intelligence/events
    GET /intelligence/{symbol}/summary
    GET /intelligence/{symbol}/news
    GET /intelligence/{symbol}/corporate-actions

Admin-protected live refresh:

    POST /intelligence/refresh

Example refresh:

    {
      "symbols": ["TCS", "INFY"],
      "domains": ["news", "corporate_actions"],
      "days": 120
    }

A refresh accepts 1-50 symbols. Corporate-action provider windows are constrained to 1-365 days.

## Canonical evidence store

R68.5 adds:

    intelligence_events

The table contains normalized evidence for both domains:

- deterministic event key
- domain
- symbol
- event type
- headline
- summary
- source
- publisher
- URL
- event timestamp
- sentiment label
- sentiment score
- impact score
- raw/source details JSON
- fetched timestamp

Deterministic SHA-256 event keys make refresh idempotent. The same source event updates its persisted evidence instead of multiplying duplicate rows.

The older news and corporate_actions tables are left intact for compatibility.

## News methodology

R68.5 consumes the existing canonical NewsService/provider boundary.

News scoring is:

    keyword_heuristic_v1

The existing positive and negative keyword sets score the headline. The result is bounded to -10..+10.

Breaking-news status is also keyword-driven from the existing BREAKING_KEYWORDS set.

R68.5 explicitly reports:

    ai_sentiment: false

The dashboard must therefore present the score as deterministic triage metadata, not AI-derived sentiment or a trade signal.

## Corporate-action methodology

R68.5 consumes the canonical CorporateActionService/provider boundary.

The service now requests corporate actions using both symbol and provider window when the provider supports that contract, while retaining a TypeError compatibility fallback for legacy no-argument providers.

The cache is keyed by:

    symbol + days

so a 30-day response cannot be incorrectly reused for a later 365-day request.

Scoring is:

    event_weight_heuristic_v1

Existing event weights are preserved, including:

- BUYBACK +9
- BONUS +8
- MERGER +8
- ACQUISITION +8
- STOCK SPLIT / SPLIT +7
- DIVIDEND +5
- PENALTY -6
- DEFAULT -8
- INSOLVENCY -10
- DELISTING -10

Multiple matched terms can contribute before the result is bounded to -10..+10.

Corporate-action responses also report high-impact event count, upcoming event count, and the next persisted future event timestamp when parseable.

## Combined intelligence score

The symbol summary exposes a diagnostic score on -10..+10.

When both domains contain persisted evidence:

    news weight = 0.4
    corporate-action weight = 0.6

When only one domain has evidence, the available domain is normalized to full weight instead of being diluted by an absent zero-score domain.

The result is explicitly labeled:

    heuristic_evidence_summary_not_trade_signal

## Webapp

### News Intelligence

- readiness/provider/scoring diagnostics
- symbol selector
- news-only refresh
- optional full intelligence refresh
- positive/negative/neutral counts
- breaking-news count
- average impact
- combined symbol intelligence score
- persisted evidence table
- CSV export
- latest cross-symbol persisted news table
- methodology disclosure

### Corporate Actions

- readiness/provider/scoring diagnostics
- symbol selector
- provider window selector
- corporate-action-only refresh
- optional full intelligence refresh
- positive/negative/high-impact counts
- upcoming count and next event
- average impact
- persisted evidence table
- CSV export
- latest cross-symbol action table
- event-weight disclosure

The Command Center surfaces persisted intelligence counts and confirms whether AI sentiment is enabled.

## Safety and operational boundary

R68.5:

- does not place broker orders
- does not create paper positions
- does not alter scanner score rules
- does not use an LLM sentiment classifier
- does not trigger live providers from GET dashboard reads
- protects only POST /intelligence/refresh with the production admin key

The intelligence_events table is SQLite-backed. The existing Render ephemeral-storage limitation remains until durable backend storage is configured.
