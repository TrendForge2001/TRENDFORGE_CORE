# B07 — CI security and release evidence

**B07a follow-up:** the current candidate replaces the used SDK transport subset,
removes the affected dependency tree and passes a complete 64-package advisory
scan. See [B07a remediation and acceptance](B07A_KITE_SDK_REMEDIATION.md).
The B07 findings and failed report below describe commit `5dffdbf` and are
retained as historical evidence. Remote release verification remains pending.

## Release status

B07 builds on the pending B06 broker-boundary commit `67aa524`. Neither batch
has been merged or deployed. B06's pushed branch still has no registered Actions
run; manual dispatch through the GitHub API is blocked from this workspace.

The security work also found genuine dependency release blockers. The refreshed
production graph resolves 35 of 38 unique advisory IDs reported by the initial
scan. Three unique advisory IDs remain across Autobahn and Twisted. The gate
continues to fail on these findings; no advisory suppression or risk waiver was
added. Passing application tests does not make this dependency scan pass.

## Required checks and reports

The existing Python 3.11/3.12 matrix and exact-production-lock regression job
remain required before Render verification. Two additional required jobs audit
dependencies and secrets. Their JSON reports upload even when a scan fails.
Scanner failures, missing reports and incomplete dependency coverage fail the
release check. The workflow verifies deployment; it does not configure Render's
auto-deploy policy. Releases require green branch checks before a main push.

`requirements-security.txt` pins the security tools. Dependency auditing queries
PyPI for every exact entry in `requirements-production.lock` without resolving
or installing another application graph. The wrapper validates package names,
versions, missing or duplicate entries, skipped queries and report structure.
It records the lock SHA-256, tool version, coverage, advisory IDs and fixes in
`security-reports/dependency-audit.json`. Only that reviewed summary is uploaded.
The raw `pip-audit.json` remains local to the scan; unreviewed descriptions,
skip reasons and scanner stderr are excluded from published artifacts and logs.

The secret gate scans tracked and unignored local files plus every commit reachable
from HEAD, including merge ancestors and deleted files. It uses local detection only;
it does not submit candidate credentials for network verification. Reports expose
locations, types and fingerprints, without matched values. Reviewed fixture and
header-name false positives use exact path/type/fingerprint entries with reasons.
Adding unrelated findings to that allowlist is a reviewable source change.
Shallow history, unsupported file modes, binary/non-UTF-8 content and scanner
errors deny a pass instead of silently reducing coverage. Text pattern scanning
does not establish that arbitrary encoded credentials are absent.

Ruff checks cover the FinEdge provider, broker policy and new security code/tests.
Strict Pyright analysis covers FinEdge, broker policy, dependency report handling
and the deployment verifier. This is scoped analysis, not a claim that all legacy
application modules are linted or strictly typed.

## Dependency changes and remaining findings

The candidate was resolved from Core and webapp requirements on Python 3.12.
Unaffected versions were constrained to the previous lock. Only these versions
changed: Certifi `2026.7.22` → `2026.10.19`, Pillow `12.3.0` → `13.0.0` and
Streamlit `1.66.0` → `1.66.1`. The Streamlit patch permits Pillow 13; its minimum
in the webapp compatibility requirements now reflects that patch. The refreshed
76-package graph installs successfully and passes `pip check`.

Initial audit: 76/76 packages, zero skips, 39 raw entries / 38 unique advisory
IDs. Refreshed audit: 76/76 packages, zero skips, four raw entries / three unique
IDs. PyPI repeats `PYSEC-2020-25`; that duplicate is not an additional issue.
The [recorded summary](security/B07_DEPENDENCY_AUDIT.json) includes the exact
refreshed lock digest and remains explicitly failed.

| Package | Remaining advisory | Published fix | Blocker |
| --- | --- | --- | --- |
| Autobahn 19.11.2 | `PYSEC-2020-25` / `CVE-2020-35678` | 20.12.3 | Every published KiteConnect 5.x version pins Autobahn 19.11.2 exactly. |
| Autobahn 19.11.2 | `PYSEC-2026-4027` / `CVE-2026-77528` | 26.7.1 | A compatible upstream SDK dependency change or separately reviewed replacement is needed. |
| Twisted 26.4.0 | `CVE-2026-106454` / `GHSA-8pqf-f4m5-798g` | None published | 26.4.0 remains the newest release. |

The [Twisted advisory](https://github.com/advisories/GHSA-8pqf-f4m5-798g)
affects authenticated IMAP LIST/LSUB handling. No IMAP server usage was found in
TrendForge. That surface review does not establish a patched package or waive
the gate. An [upstream fix](https://github.com/twisted/twisted/commit/2f8a3c29246f4eb324690e06a9767a11dc4aec9f)
is merged, but no patched release is listed. Removing Twisted or overriding
Autobahn's exact pin would break the supported SDK dependency contract.

## Test-client compatibility

Test-only `httpx2==2.16.0` selects Starlette's supported TestClient transport.
Production `httpx` remains installed for existing application integrations.
The specific deprecated fallback is now a test error, so missing test tooling
cannot silently restore the warning. A real ASGI request/lifespan test exercises
the supported path. Locked-production tests install `requirements-test.txt`
under the production lock's constraints so test tooling cannot upgrade a runtime
distribution. Test and security tooling are absent from the Render lock.

## Reproduction and next release gates

Local Python 3.12 validation against the refreshed exact lock: **1,624 passed,
2 skipped**, with no warnings. Compilation, `pip check`, exact installed-version
verification, deployment preflight, scoped Ruff and both strict Pyright projects
passed. The live dependency audit checked all 76 packages and failed solely on
the recorded SDK advisories. These results do not claim green remote CI or a
new production deployment.

The pre-commit secret scan passed for 818 current files and all history reachable
from `67aa524` (2,035 path/blob versions, 2,019 unique blobs), with zero unreviewed
findings. Exceptions cover exact dummy fixtures, literal header names and the
generated public lock digest. The new commit is scanned again before publication
so newly introduced historical blobs also require the reviewed policy.

Use separate virtual environments for application regression and security tools:

```sh
python -m pip install -r requirements-production.lock
python -m pip install -c requirements-production.lock -r requirements-test.txt
python -m pip check
python -m pytest -q
```

```sh
python -m pip install -r requirements-security.txt
python -m scripts.check_dependency_audit --output-dir security-reports
python -m scripts.check_secrets --output-dir security-reports
```

Remaining release work is split into reviewable batches:

1. **B07a — SDK dependency remediation.** Obtain a supported KiteConnect release
   with patched Autobahn, or review a replacement integration while preserving
   authentication, market/account reads and the B06 execution boundary. Require
   resolver consistency and fake-broker contracts; do not override exact SDK pins.
2. **B07b — Twisted patched-release verification.** Track the upstream fix, refresh
   the graph when a supported patched release is published, and rerun the complete
   advisory scan. Preserve the existing failure until then.
3. **B07c — Remote release evidence.** Obtain green Python 3.11/3.12, locked
   production, quality and security jobs on the release commit; merge and verify
   the exact Render SHA. Resolve the missing Actions trigger/API access first.

B08 then performs actual authenticated provider/browser checks, controlled
no-order scanner acceptance and cloud persistence recovery. Those checks remain
separate from local test success.
