# FinEdge provider diagnostics — 2026-10-22

The supplied source excerpt predates the backend integration on `778175c`.
The public Actions summary for that integration was successful:
https://github.com/TrendForge2001/TRENDFORGE_CORE/actions/runs/39716682057

The exact nine diagnostic messages were not supplied, so this review does not
claim a one-to-one match to that count. Checks against the current provider
reproduced strict JSON type-narrowing errors and lint issues involving import
ordering, collection typing imports, quoted annotations and long lines.

## Fix

- After runtime verification that a JSON response is an object or array, narrow
  its static type explicitly. Provider methods now return that object/array
  contract rather than an unbounded return annotation.
- Keep upstream error-envelope checks and sanitized exception handling intact.
- Sort and modernize imports and format the module consistently.
- Add `pyright-finedge.json` for strict analysis of this provider on Python 3.11.
- Add a dedicated Actions job for pinned Ruff/Pyright checks so these
  diagnostics are checked alongside runtime tests in future releases.

No type-checker suppressions were added. The existing quota, caching, token
handling, authentication and financial-data verification behavior is preserved.

Local strict typing reports zero errors/warnings; lint and formatting pass.
The full regression suite and the new remote workflow must pass before promotion
to main. Git transport can perform the merge even though GitHub API access is
blocked; the public workflow summary supplies the check evidence.

Render is configured to auto-deploy main, as shown in the supplied deployment
screenshot. A main-branch update is the available deploy trigger. Public Render
verification from this environment currently fails at the network proxy with
CONNECT 403, so live deployment success cannot be inferred from a successful push.

## Follow-up runtime fixes and deployment verification

The subsequent review found two additional edge cases: long/date-form
Retry-After headers were shortened, and explicit `from_env()` overrides could
duplicate constructor keywords. Both now have regression coverage and fixes.
Empty rate-limit settings use the documented default; malformed settings return
a sanitized configuration error.

A main-only post-CI job now verifies the deployed SHA and both liveness and UI
responses from the GitHub runner. It makes only public GET requests and prints
status codes and validated commit hashes, not raw health data or credentials.
