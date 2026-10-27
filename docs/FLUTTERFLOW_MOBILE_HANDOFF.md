# TrendForge personal Android app: FlutterFlow handoff

Prepared 26 October 2026 against backend release
`059f76c31f0b8f3cd167b5017031e5730e05ac8a`.

This is a development specification, not a generated FlutterFlow project or an
installable APK. The Streak application screenshots are visual/interaction
references ONLY. Do not copy their scanner catalog, strategy catalog, indicators,
thresholds, signals or trading rules. The owner's separate analysis/notebook
material supplies the trading specification. The existing analysis-derived
registry supplies the current implementation mapping;
this handoff does not claim to have independently re-inspected every original
image. Do not ask the owner to rewrite the supplied analysis. Record any specific
conflict against its source before changing execution behaviour.

## Architecture and current readiness

```text
Android app built with FlutterFlow
  -> HTTPS mobile API adapter, authenticated as the owner
    -> existing FastAPI scanner, backtest and paper services
      -> persistent database and server-side workers
      -> Kite market-data/session integration
```

The app must not call privileged Core APIs with an embedded Admin key. Firebase
owner verification and the mobile session/readiness reads are now implemented;
the proposed trading/job adapters below remain NEW WORK. Existing Core endpoint mappings are in
[mobile/core-api-reference.json](mobile/core-api-reference.json); that file is a
reference manifest, not a FlutterFlow import format or a replacement for OpenAPI.

| Prerequisite | Current evidence | Remaining action |
|---|---|---|
| FlutterFlow project and GitHub | No project or export is attached to this workspace | Owner creates the project and connects a dedicated mobile repository; share its project link or exported code through the available development workflow |
| Android private release | No Flutter project, keystore or APK exists here | Configure application ID, generate and back up the signing key outside Git, build and install a signed APK |
| Always-on persistent backend | Root Render configuration is free with no disk; strict mounted-book launcher and paid review template now exist | Configure always-on compute, preserve the existing book, attach durable storage and verify restart recovery |
| Mobile authentication | Firebase owner verification and session/readiness reads exist, disabled until configured; Core Admin auth stays separate | Configure Firebase/FlutterFlow owner login and build the allowlisted mobile trading adapter before connecting privileged controls |
| Kite data | Profile/quote diagnostics and read-only readiness exist | Verify the deployed service's credentials and market-data permissions; implement and test token-renewal handling |
| Scanner, backtest and paper APIs | Core routes exist | Add mobile response contracts, authorization, background-job persistence and operation reconciliation |
| Device acceptance | Existing tests exercise Python/Streamlit | Execute the Android acceptance checks below on a real phone |

No accounts, paid infrastructure, Firebase configuration or signing credentials
have been created by this handoff. Account/project setup uses the service's
normal invitation or repository access flow; never paste secret values in chat.

## Screen definitions

Preserve the five existing workspaces as five mobile destinations. Use the
Streak references for list/detail hierarchy and interactions, with TrendForge
branding, readable stock rows and the existing dark palette. Settings and
strategy details are child screens rather than extra first-level tabs.
The three supplied Home/Scanners/Strategies examples are mapped to FlutterFlow
components in [the UI reference brief](mobile/FLUTTERFLOW_UI_REFERENCE.md).

| Destination | Components and actions |
|---|---|
| Watchlist | Nifty index/sector dropdown, constituent search, price/change, quote timestamp, data status and per-stock score with scanner provenance; tap stock for chart/details |
| Scanner | Searchable six-source-plus-two-short catalog, Intraday/Swing/Medium–Long filters, selected universe, indicator chips, View Conditions, Run Scan, matching stocks with individual scores; select BUY/SELL entry candidates for paper handoff or backtest |
| Backtesting | Candidate universe and strategy, history/costs, shared ₹1,00,000 account with ₹80,000 deployment cap/₹20,000 reserve/three concurrent stocks, score-proportional allocation, per-stock P&L, trade ledger, equity/P&L charts and export |
| Paper Trading | Explicit automation status and target scope, blocker explanations, Start/Stop, separate kill switch, open positions, last-mark time, realized/unrealized P&L and strategy statements |
| Kite Session | Authentication and quote freshness, read-only account/session information and trading-preparation checks; live order submission stays locked |

Separate states on every network-backed screen: initial, loading, completed with
data, completed with no matches, partially failed, unavailable, unauthorized and
stale. Missing quotes/scores are unavailable, never zero. A high score is not
permission to trade. Display server confirmation after Start/Stop; do not show
ON merely because the button was tapped.

## Source strategies

These are the owner's existing TrendForge analysis-derived definitions, not
presets copied from the Streak screenshots. This design clarification does not
authorize adding, removing or changing a trading rule.

Use stable backend IDs, not names as request identifiers. Read names, indicators,
conditions and eligibility from `/technical/strategies` rather than implementing
a second strategy engine in Dart.

| ID | Interval | Current execution status |
|---|---|---|
| `tf_intraday_ema9_20_momentum` | 15 minutes | Deterministic evaluator; subject to validation/risk gates |
| `tf_intraday_vwma9_26_rsi_volume` | 15 minutes | Deterministic evaluator; subject to validation/risk gates |
| `tf_swing_ema20_50_rsi_volume` | Daily | Deterministic evaluator; subject to validation/risk gates |
| `tf_swing_vwma9_26_rsi_volume` | Daily | Deterministic evaluator; subject to validation/risk gates |
| `tf_medium_ema50_100` | Daily/weekly source context | Review required; entry/backtest disabled |
| `tf_long_ema100_200` | Daily/weekly source context | Review required; entry/backtest disabled |

See [SOURCE_SIX_CATALOG.md](SOURCE_SIX_CATALOG.md) for existing source ambiguities
and exit-only compatibility for historical positions. Do not infer undefined
medium/long-term stops, targets or confirmation rules to make buttons executable.

Universe choices come from `config/nifty_universes.py`: broad Nifty 50/100/200/500,
LargeMidcap 250, Midcap 150/Select, Smallcap 250, Microcap 250 and Bank, Financial
Services, IT, Auto, FMCG, Pharma, Metal and Realty. Grouped LargeMidcap uses the
same membership with sector grouping. Official membership failures must remain
visible. Scanner-derived paper targets are currently limited to NIFTY 500
membership and at most 100 selected stocks.

## Authentication implementation and pending API adapter

Recommended initial identity integration: Firebase Authentication with the
owner's approved account only. The server-side Firebase ID-token verifier is
implemented in `services/mobile_identity.py`. Firebase account configuration and
FlutterFlow integration still need to be completed; a login screen alone provides
no Core authorization. Do not ship a public self-registration UI.

The new adapter must verify the token's signature, issuer, audience, expiry,
revocation policy and owner UID on each privileged request. Reject other valid
Firebase users. Use HTTPS and SDK-managed session handling with platform-backed
secure storage for sensitive session material. Sign-out clears local protected
data; never persist financial responses in ordinary app state across logout.

Expose only explicitly mapped mobile operations. Do not create an arbitrary
URL/header forwarding proxy. Prefer invoking the existing service layer after
owner authorization. If a server-to-server Core call is needed, its Admin key
stays in backend secret settings. All existing storage, risk, strategy and
broker-execution guards remain in force. Private paper/account responses must
not be served from shared caches. Audit Start/Stop without logging tokens.

The current Streamlit Manual Access Key and Admin header are not mobile bearer
authentication. Native Android calls do not need CORS; configure explicit allowed
origins separately if publishing a Flutter web preview.

## Mobile operations and background work: implementation required

Proposed routes under `/mobile/v1` are design targets, NOT current APIs:

- `POST /scan-jobs` and `GET /scan-jobs/{job_id}`.
- `POST /backtest-jobs` and `GET /backtest-jobs/{job_id}`.
- `GET /paper/status` and `PUT /paper/automation`.
- `GET /operations/{operation_id}` for uncertain control outcomes.
- `GET /paper/strategy-pnl` and `GET /kite/readiness`.

Return job/operation identifiers and timestamps; persist requests, progress,
results, partial errors and cancellation/recovery state. Enforce owner scope on
every job read. The current shared-account portfolio backtest is one synchronous
Core request and its completed result is persisted. It still needs a durable
mobile job/progress protocol to reconcile an app closure or lost response.
Legacy independent stock allocations must not be labelled a shared-capital
portfolio. Follow the server-owned policy in
[THREE_STOCK_PORTFOLIO.md](THREE_STOCK_PORTFOLIO.md).

Use an idempotency key for each mobile Start/Stop intent and job submission,
persist the result and reject reuse with a different payload. This is new work:
the existing Core automation PUT is not a durable mobile operation protocol.
Do not treat an existing scan/backtest `run_id` as proven generic idempotency.
After a timeout, reconcile the operation/status rather than blindly retrying a
mutation. Disable duplicate taps while a request is outstanding. A later Stop
must defeat any earlier pending Start, including across adapter retries/restarts.

Paper Start payloads carry scope only: universe, strategy IDs and selected
symbols. Fresh signals, candles, quotes, sizing, stops and approval come from the
server. Stop blocks new entries and keeps existing-position monitoring/exits;
it is not liquidation. Server restart always leaves automatic entries OFF.
The worker must remain active with the phone locked, offline or the app closed.

Poll read-only job/status APIs while a screen is active with bounded backoff;
avoid provider calls on every widget rebuild. Push notifications are additional
work: register device tokens per owner, implement a server-side event outbox and
deduplication, and handle revoked tokens/notification permissions. A push message
is informational and cannot itself authorize a fill.

## Storage and market-data activation

Follow [PAPER_STORAGE_SETUP.md](PAPER_STORAGE_SETUP.md#render-storage-alternative).
Preserve existing ledger records before changing infrastructure, verify the
mounted database and restart recovery, then confirm restoration, worker,
strategy validation and quote readiness. A recovery flag alone is insufficient.
Do not enable ephemeral simulation as a substitute for the selected durable
operating mode. Paid provisioning remains an owner account action.

Keep Kite API secret/access tokens on the backend. Any mobile broker-login flow
must complete token exchange on the server using registered redirect settings;
never collect the broker password or embed the secret in the APK. Existing
manual access-token updates remain a supported operating step until renewal is
implemented. No current claim is made that unattended renewal exists.

Display timezone-aware trade timestamps in `Asia/Kolkata` as
`DD Mon YYYY, HH:mm:ss IST`, preserving raw values in exports. A daily candle is
a date, not an invented exact fill time. Device timezone must not change trading
windows: current automatic entry window is weekdays 09:30–14:45 IST, with
strategy-specific restrictions and freshness checks still applied. These hours
alone do not prove that an exchange session is open. Keep server-side session
and quote checks authoritative.

## Development batches and completion criteria

| Batch | Deliverable | Acceptance |
|---|---|---|
| M01 | This handoff and verified Core API inventory | Existing/proposed APIs and source-rule limitations clearly separated |
| M02 | Persistent hosted runtime and backup/recovery procedure | Ledger survives a controlled restart; storage/restore gates pass; no auto-resume |
| M03 | Owner login and mobile API authorization | Owner succeeds; missing/expired/revoked/non-owner tokens fail; no embedded Admin/Kite secrets |
| M04 | FlutterFlow five-screen shell, source catalog and data bindings | Nifty lists, conditions, per-stock scores and all network states render on Android |
| M05 | Durable scan/backtest jobs and P&L views | Work survives app closure/server restart according to documented recovery policy; partial failures and cost-adjusted results remain explicit |
| M06 | Paper controls, status reconciliation and notifications | Duplicate taps/timeouts cannot duplicate fills; Stop wins over pending Start; device closure does not stop the server worker |
| M07 | Signed private Android release | Acceptance matrix passes; signing backup and reproducible release instructions exist |

M01 is supplied by this document. M02 now has an optional strict persistent
launcher/template, and M03 has Firebase owner verification plus protected mobile
session/readiness reads. Their account provisioning and real-device acceptance
remain pending; see [M02/M03 operations](M02_M03_OPERATIONS.md). Mobile trading
adapters, UI and durable jobs are still future work. Real broker order execution remains a later,
separately authorized development scope: see
[LIVE_PAPER_OPERATIONS.md](LIVE_PAPER_OPERATIONS.md#kite-live-trading-preparation).

## Android acceptance and release checklist

- Compare implemented screens with the supplied references at phone sizes;
  inspect touch targets, keyboard behaviour, scrolling and large font settings.
- Exercise Wi-Fi/mobile handover, offline/reconnect, 401, 429, 502/503/504 and
  timeouts before/after a command is accepted. No blind mutation replay.
- Submit duplicate Start/Stop/job requests, issue Stop while Start is pending,
  and kill/reopen the app. Reconcile actual server state.
- Test storage unavailable/restart restoration, stale quotes, rejected strategy,
  kill switch, expired Kite token, market closure and risk rejection. No fill
  may bypass a blocker.
- Verify ledger/P&L per strategy, transaction-cost treatment, missing/invalid
  times and IST display with the device set to another timezone. Preserve
  spreadsheet formula protection in any CSV/XLSX export implementation.
- Reproduce the current selection-bias warning for today's scanner picks tested
  against historical prices; don't label it a point-in-time portfolio backtest.
- Confirm a non-owner cannot read another account/job and logout clears protected
  app state. Inspect exported code/APK and logs for embedded secrets.
- Configure a stable Android application ID and release version; keep signing
  keys and their backup outside Git. Build a signed release APK, install it on
  the owner's phone and verify an update preserves the intended app identity.
- Record backend revision, mobile revision, build instructions, test evidence
  and rollback procedure before enabling supervised paper use.
