# Audit hardening review

This review applies to the audit branch stacked on the approved EMA horizon
revision. It is a source proposal only. No merge, Blueprint sync, deployment,
service suspension, account-limit change or paper Start was performed.

## Changes and remaining operational work

| Finding | Source change or verified status | Remaining work |
|---|---|---|
| Commit-triggered restarts | `render.yaml` requests manual deployment with `autoDeployTrigger: "off"`. The branch does not change restart-to-OFF behavior. | Live auto-deploy is still `commit`. The connected Render toolset cannot update a web service's deploy trigger; apply the setting separately before merging. |
| 512 MB memory headroom | Validation already admits one worker. Render validation candle batches now cap at five symbols even when a request asks for 25/50. A real pipeline test checks that all 13 synthetic instruments are retained while provider batches stay at most five. | No compute upgrade was purchased. Full-universe peak RSS and production headroom remain unverified; a batch cap is not an OOM guarantee. |
| Holiday freshness | Prior/next/completed-session helpers share the configured operational holiday and special-date calendar. Live scanners, paper admission/start checks, staged next-session windows, disclosure confirmation and historical cutoff selection no longer maintain separate weekday approximations. | This uses configured dates, not a newly fetched official exchange-calendar feed. Current-year holiday completeness and nonstandard special-session hours are not certified. |
| Launch-dependent risk defaults | Direct auto-entry construction now loads defaults from the validated PC policy: three positions, six daily entries, 3% realized-plus-open loss, and the policy's zero reserve. Missing entry-count/P&L evidence blocks entries; tests now supply real evidence instead of relying on unlimited-entry defaults. | Explicit environment overrides remain supported. Saved production risk settings were not changed. |
| RSI ambiguity | All 21 current public strategy definitions already use Wilder RSI where RSI is required. A regression checks public metadata and compares the active calculation with an independent seeded recursion. Frozen historical rolling-RSI definitions stay available for historical lineage. No thresholds were optimized. | Comparison against a current Kite chart remains unverified because market candles/chart data were unavailable here. |
| Dead modules | Removed the eight identified unreferenced modules/placeholders, including both unused APScheduler wrappers. Full-suite regression passes without adding APScheduler. | None in the identified removal list. |
| Dependency/config drift | Both runtime locks pin NumPy 2.4.6. The full suite has no NumPy deprecation-warning flood. The active Blueprint reflects the existing Starter/0.5 CPU 512 MB service, Oregon, one instance and its 1 GB `/var/data` disk. | Current Render documentation/schema endpoints were inaccessible in this environment. YAML/config parsing passed; a remote Blueprint plan was not applied or represented as validated. |
| Old public services | Render confirms staging and the artifact bridge still exist, are not suspended and have auto-deploy disabled. | No supported suspension tool is connected, and continued use was not established. Review/suspend them in Render separately; neither was deleted. |

## Historical admission and evidence

Admission policy `approved-paper-admission-v3-calendar` captures calendar dates
alongside the saved account limits and costs. Historical admission reads this
frozen snapshot instead of the current database. Calendar changes alter the
policy fingerprint. `strategy-v14-calendar-admission-alignment` invalidates
older promotion evidence. Existing positions retain their frozen exit lineage.
This revision does not start paper trading or change any approved entry/exit
threshold beyond the separately approved EMA horizon revision.

The full-suite run also exposed a UTC/IST boundary bug in institutional trade
comparison: disclosure windows used the request's IST date, while the final
comparison used host `date.today()`. Comparison now accepts the request cutoff
explicitly; a midnight-boundary regression verifies the same date reaches it.
This does not convert holdings into actual trades or bypass a blocked source.

## Verification

- CPython 3.12; pandas 2.3.3; NumPy 2.4.6.
- Full suite: 3,206 passed, four skipped, zero failed. Synthetic tests are not
  market backtests, production memory evidence, or paper/live qualification.
- Production lock: 68 packages checked; no known dependency vulnerabilities.
- Python/config parsing and release lint/format checks were run on the branch.
- Private owner tradebooks, execution charts, account information and derived
  strategy research are excluded from this source branch and its public PR.

## No deployment

The live service remains on its existing main-branch commit. All live operational
items above remain pending; editing this file or opening a PR does not apply
them. Do not merge the stacked PRs or sync the Blueprint until the owner separately
authorizes a deployment window and the operational settings are reviewed.
