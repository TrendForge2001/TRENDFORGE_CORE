# Render startup timeout investigation — 2026-10-21

## Observed failure

The supplied Render logs are for main commit `2cd97db`, not the newer safety
and design release branch. Dependency installation and build upload succeeded.
Uvicorn was launched at 22:29:07 IST. Render reported no open ports at 22:43:50
IST and timed out at 22:46:45 IST. There is no `Started server process` or
`Application startup complete` message in the supplied runtime excerpt.

This establishes a failure before normal HTTP serving; it does not identify
the precise blocking import or prove a port configuration error. The configured
command binds `0.0.0.0:$PORT` and matches the manifest. Increasing a health-check
timeout would not identify why the process never opened a listening socket.

## Reproductions and changes

1. A local unified cold boot with the production dependency lock, temporary
   database and no broker credentials became live in about 2.3 seconds before
   these fixes. The Render stall itself was not reproduced with that setup.
2. A separate liveness defect was reproduced: occupying the synchronous worker
   limiter made `/livez` time out while the outer async `/health` returned 200.
   `/livez` is now async in Core and explicitly registered on the outer unified
   application, ahead of the mounts. GET and HEAD are supported. This removes
   worker-pool dependency after startup; it cannot open a port before startup.
3. The Streamlit entry script now uses an absolute path derived from this
   repository. Relative paths were shown to resolve incorrectly after Streamlit
   sets its main-script configuration. This is an independent path fix, not a
   confirmed explanation for this Render incident.
4. `start.py` now wraps app import with a production-only diagnostic context.
   It emits flushed `TRENDFORGE_BOOT` start/complete markers and elapsed time.
   After 60 seconds of stalled import, Python dumps thread stacks repeatedly
   until import completes or fails. It does not print environment variables or
   local variable contents. The timer is cancelled on completion/failure.

Startup still waits for required initialization. No partial application is
reported ready, and database initialization failures continue to fail startup.
The active free plan, port binding command and `/livez` health path are unchanged.

Validation: 1,277 tests passed, 2 skipped, with the existing Starlette/httpx
deprecation warning. Compilation, deployment preflight and whitespace checks
passed. A real local Uvicorn unified cold boot completed in 2.43 seconds;
GET/HEAD `/livez` and `/app/` each returned 200. Production import markers
reported completion in 1.568 seconds. Worker-capacity isolation and watchdog
timer cancellation have dedicated regression coverage.

## Next deployment evidence

After GitHub checks pass, deploy the release commit containing these changes.
Verify the deployed SHA rather than retrying the old main revision.

- No `TRENDFORGE_BOOT ... status=starting`: failure is before the ASGI import
  wrapper; inspect the runtime command, Python/Uvicorn loading and instance logs.
- `starting` without `complete`: collect the watchdog stacks after 60 seconds.
  They identify the code location blocked during application import/composition.
- `complete` followed by `Waiting for application startup` without completion:
  inspect initialization/bootstrap/scheduler startup and available resources.
- `Uvicorn running on ...` present: probe GET/HEAD `/livez` and `/app/`, confirm
  the bound port equals Render's supplied `PORT`, and inspect request logs.

The current environment cannot query Render or GitHub Actions APIs because of
network `403 Forbidden` responses. The fix can be pushed through Git transport,
but a successful Render deployment must be established from new deploy logs.
